/// Client of the EXISTING Channels endpoint `ws/v1/realtime/` (ADR 0015) —
/// same protocol as the desktop (school_admin/realtime.py):
///
///   connection  handshake with `Authorization: Bearer <access>` -> "auth.ok"
///   resync      after every (re)connection: "sync" since the last notification
///               seen, "subscribe" (+ since) for the watched conversations
///   keep-alive  "ping" every 25 s
///   close 4401  expired token / revoked session / suspended member:
///               one refresh through the REST client, else [sessionExpired]
///   other drops reconnection with backoff (1, 2, 4 ... 30 s)
library;

import 'dart:async';
import 'dart:convert';

import 'package:web_socket_channel/io.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

import '../api/api_client.dart';
import '../l10n/l10n.dart';

const unauthorizedClose = 4401;
const _backoff = [1, 2, 4, 8, 15, 30];

enum RealtimeState { stopped, connecting, online, offline, expired }

typedef ChannelFactory = WebSocketChannel Function(Uri uri, Map<String, String> headers);

WebSocketChannel _ioChannel(Uri uri, Map<String, String> headers) => IOWebSocketChannel.connect(uri, headers: headers);

/// 'http://h:8000/api/v1/' -> 'ws://h:8000/ws/v1/realtime/' (wss for https).
Uri socketUri(String apiUrl) {
  final api = Uri.parse(apiUrl);
  return api.replace(scheme: api.scheme == 'https' ? 'wss' : 'ws', path: '/ws/v1/realtime/', query: null);
}

class RealtimeClient {
  RealtimeClient(
    this.api,
    this.uri, {
    ChannelFactory channelFactory = _ioChannel,
    this.pingInterval = const Duration(seconds: 25),
    Future<bool> Function()? refresh,
  }) : _factory = channelFactory,
       _refresh = refresh ?? (() async => false) {
    L10n.changes.addListener(_languageChanged);
  }

  final ApiClient api;
  final Uri uri;
  final Duration pingInterval;
  final ChannelFactory _factory;
  final Future<bool> Function() _refresh;

  final _states = StreamController<RealtimeState>.broadcast();
  final _notifications = StreamController<Map<String, dynamic>>.broadcast();
  final _unread = StreamController<int>.broadcast();
  final _messages = StreamController<Map<String, dynamic>>.broadcast();
  final _expired = StreamController<void>.broadcast();

  Stream<RealtimeState> get states => _states.stream;
  Stream<Map<String, dynamic>> get notifications => _notifications.stream;
  Stream<int> get unreadNotifications => _unread.stream;
  Stream<Map<String, dynamic>> get messages => _messages.stream;
  Stream<void> get sessionExpired => _expired.stream;

  RealtimeState state = RealtimeState.stopped;
  String? lastSeen;
  final Map<String, String?> watched = {};
  int _attempt = 0;
  bool _refreshed = false;
  WebSocketChannel? _channel;
  StreamSubscription<dynamic>? _subscription;
  Timer? _ping;
  Timer? _retry;

  void start() {
    final token = api.accessToken;
    if (token == null) {
      _set(RealtimeState.expired);
      _expired.add(null);
      return;
    }
    _drop();
    _set(RealtimeState.connecting);
    // the server renders system notifications in this language
    final channel = _factory(uri, {'Authorization': 'Bearer $token', 'Accept-Language': L10n.language.code});
    _channel = channel;
    _subscription = channel.stream.listen(
      (event) => _onFrame('$event'),
      onDone: () => _onClosed(channel.closeCode),
      onError: (_) => _onClosed(null),
      cancelOnError: true,
    );
  }

  void stop() {
    _retry?.cancel();
    _drop();
    _set(RealtimeState.stopped);
  }

  /// A new language: reconnect, so live notifications come in it.
  void _languageChanged() {
    if (state == RealtimeState.online || state == RealtimeState.connecting) {
      scheduleMicrotask(() {
        if (state != RealtimeState.stopped) start();
      });
    }
  }

  Future<void> dispose() async {
    L10n.changes.removeListener(_languageChanged);
    stop();
    for (final controller in [_states, _notifications, _unread, _messages, _expired]) {
      await controller.close();
    }
  }

  void watch(String conversationId, {String? since}) {
    watched[conversationId] = since ?? watched[conversationId];
    if (state == RealtimeState.online) _subscribe(conversationId);
  }

  void unwatch(String conversationId) {
    watched.remove(conversationId);
    send({'type': 'unsubscribe', 'conversation': conversationId});
  }

  void send(Map<String, dynamic> frame) {
    if (state == RealtimeState.online) _channel?.sink.add(jsonEncode(frame));
  }

  // --- internals ---------------------------------------------------------------------

  void _set(RealtimeState next) {
    if (next == state) return;
    state = next;
    if (!_states.isClosed) _states.add(next);
  }

  void _drop() {
    _ping?.cancel();
    _subscription?.cancel();
    _subscription = null;
    _channel?.sink.close();
    _channel = null;
  }

  void _subscribe(String conversationId) {
    final frame = <String, dynamic>{'type': 'subscribe', 'conversation': conversationId};
    final since = watched[conversationId];
    if (since != null) frame['since'] = since;
    send(frame);
  }

  Future<void> _onClosed(int? code) async {
    _ping?.cancel();
    if (state == RealtimeState.stopped) return;
    _subscription = null;
    _channel = null;
    if (code == unauthorizedClose) {
      if (!_refreshed && await _refresh()) {
        _refreshed = true;
        start();
        return;
      }
      _set(RealtimeState.expired);
      _expired.add(null);
      return;
    }
    _set(RealtimeState.offline);
    final delay = _backoff[_attempt < _backoff.length ? _attempt : _backoff.length - 1];
    _attempt++;
    _retry?.cancel();
    _retry = Timer(Duration(seconds: delay), start);
  }

  void _onFrame(String text) {
    Map<String, dynamic> frame;
    try {
      frame = (jsonDecode(text) as Map).cast<String, dynamic>();
    } on FormatException {
      return;
    }
    switch (frame['type']) {
      case 'auth.ok':
        _attempt = 0;
        _refreshed = false;
        _set(RealtimeState.online);
        _ping?.cancel();
        _ping = Timer.periodic(pingInterval, (_) => send({'type': 'ping'}));
        _unread.add((frame['unread_notifications'] as int?) ?? 0);
        send({'type': 'sync', if (lastSeen != null) 'since': lastSeen});
        for (final conversation in watched.keys.toList()) {
          _subscribe(conversation);
        }
      case 'notification':
        final data = ((frame['data'] as Map?) ?? const {}).cast<String, dynamic>();
        lastSeen = (data['created_at'] as String?) ?? lastSeen;
        _notifications.add(data);
      case 'sync':
        final rows = ((frame['notifications'] as List?) ?? const []).cast<Map>();
        if (rows.isNotEmpty) lastSeen = (rows.last['created_at'] as String?) ?? lastSeen;
        for (final row in rows) {
          _notifications.add(row.cast<String, dynamic>());
        }
        _unread.add((frame['unread_notifications'] as int?) ?? 0);
      case 'subscribed':
        final rows = ((frame['messages'] as List?) ?? const []).cast<Map>();
        final conversation = '${frame['conversation']}';
        if (rows.isNotEmpty && watched.containsKey(conversation)) {
          watched[conversation] = rows.last['created_at'] as String?;
        }
        for (final row in rows) {
          _messages.add(row.cast<String, dynamic>());
        }
      case 'message.created':
        final data = ((frame['data'] as Map?) ?? const {}).cast<String, dynamic>();
        final conversation = '${data['conversation']}';
        if (watched.containsKey(conversation)) watched[conversation] = data['created_at'] as String?;
        _messages.add(data);
    }
  }
}
