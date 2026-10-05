/// Live state of a signed-in session, shared by every app's shell: the
/// existing ws/v1/realtime/ connection (RealtimeClient: reconnection, resync,
/// 4401 -> one refresh then expiry), unread count, pushed notifications and
/// messages. A route opened above the shell gets it back with [openAbove].
library;

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:provider/provider.dart';

import '../auth/auth_service.dart';
import '../realtime/realtime_client.dart';

final hm = DateFormat('HH:mm', 'fr_FR');
final dayLong = DateFormat('EEEE d MMMM', 'fr_FR');
final dayShort = DateFormat('EEE d MMM', 'fr_FR');
final dateOnly = DateFormat('dd/MM/yyyy', 'fr_FR');
final dateTime = DateFormat('dd/MM/yyyy HH:mm', 'fr_FR');

String capitalize(String text) => text.isEmpty ? text : '${text[0].toUpperCase()}${text.substring(1)}';

class LiveState extends ChangeNotifier {
  int unread = 0;
  RealtimeState connection = RealtimeState.stopped;
  final notifications = StreamController<Map<String, dynamic>>.broadcast();
  final messages = StreamController<Map<String, dynamic>>.broadcast();
  RealtimeClient? client;
  final _subscriptions = <StreamSubscription<dynamic>>[];

  /// Starts [realtime] for the session; an expired socket session expires
  /// the app's session too.
  void attach(RealtimeClient realtime, AuthService auth) {
    client = realtime;
    _subscriptions
      ..add(realtime.states.listen(setConnection))
      ..add(realtime.unreadNotifications.listen(setUnread))
      ..add(
        realtime.notifications.listen((n) {
          notifications.add(n);
          if (n['is_read'] != true) setUnread(unread + 1);
        }),
      )
      ..add(realtime.messages.listen(messages.add))
      ..add(realtime.sessionExpired.listen((_) => auth.expire()));
    realtime.start();
  }

  /// Back in the foreground: reconnect at once (the resync fetches what was missed).
  void resume() {
    final realtime = client;
    if (realtime != null && realtime.state != RealtimeState.online) realtime.start();
  }

  void setUnread(int value) {
    unread = value < 0 ? 0 : value;
    notifyListeners();
  }

  void setConnection(RealtimeState value) {
    connection = value;
    notifyListeners();
  }

  @override
  void dispose() {
    for (final s in _subscriptions) {
      s.cancel();
    }
    client?.dispose();
    notifications.close();
    messages.close();
    super.dispose();
  }
}

/// Opens [screen] above the shell: routes are pushed on the app's navigator,
/// outside the shell's providers, so the live state (and [extra] providers
/// of the app, e.g. the selected child) are provided again.
Future<T?> openAbove<T>(
  BuildContext context,
  Widget screen, {
  List<ChangeNotifierProvider<ChangeNotifier>> Function(BuildContext context)? extra,
}) {
  final live = context.read<LiveState>();
  final more = extra?.call(context) ?? const [];
  return Navigator.of(context).push<T>(
    MaterialPageRoute(
      builder: (_) => MultiProvider(
        providers: [
          ChangeNotifierProvider<LiveState>.value(value: live),
          ...more,
        ],
        child: screen,
      ),
    ),
  );
}

/// Connection indicator for app bars.
class LiveIndicator extends StatelessWidget {
  const LiveIndicator({super.key});

  @override
  Widget build(BuildContext context) {
    final live = context.watch<LiveState>();
    if (live.client == null) return const SizedBox.shrink();
    final online = live.connection == RealtimeState.online;
    return Padding(
      padding: const EdgeInsets.only(right: 8),
      child: Tooltip(
        message: online ? 'Connecté en direct' : 'Hors ligne : reconnexion automatique',
        child: Icon(online ? Icons.wifi_tethering : Icons.wifi_off, size: 20),
      ),
    );
  }
}

void showMessage(BuildContext context, String text) {
  ScaffoldMessenger.of(context)
    ..hideCurrentSnackBar()
    ..showSnackBar(SnackBar(content: Text(text)));
}
