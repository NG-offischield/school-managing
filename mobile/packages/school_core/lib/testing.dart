/// Test helpers for the apps' widget tests (not part of the runtime API):
/// an in-memory WebSocket channel for RealtimeClient.
library;

import 'dart:async';
import 'dart:convert';

import 'package:web_socket_channel/web_socket_channel.dart';

class FakeChannel implements WebSocketChannel {
  final incoming = StreamController<dynamic>();
  final sent = <Map>[];
  int? code;
  late final _FakeSink _sink = _FakeSink(this);

  /// The server sends a frame.
  void push(Map frame) => incoming.add(jsonEncode(frame));

  /// The server closes the socket (4401 = session refused).
  void closeWith(int closeCode) {
    code = closeCode;
    incoming.close();
  }

  @override
  Stream get stream => incoming.stream;

  @override
  WebSocketSink get sink => _sink;

  @override
  int? get closeCode => code;

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

class _FakeSink implements WebSocketSink {
  _FakeSink(this.channel);

  final FakeChannel channel;

  @override
  void add(dynamic data) => channel.sent.add(jsonDecode('$data') as Map);

  @override
  Future close([int? closeCode, String? closeReason]) async {}

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}
