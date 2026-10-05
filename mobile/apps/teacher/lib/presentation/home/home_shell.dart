import 'dart:async';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:school_core/school_core.dart';

import '../communication/communication_screen.dart';
import '../dashboard/dashboard_screen.dart';
import '../planning/planning_screen.dart';
import '../profile/profile_screen.dart';

/// Signed-in shell: 4 tabs (Accueil, Planning, Communication, Profil) and the
/// live connection (existing ws/v1/realtime/) for the whole session.
class HomeShell extends StatefulWidget {
  const HomeShell({super.key, this.realtime});

  final RealtimeClient Function()? realtime;

  @override
  State<HomeShell> createState() => _HomeShellState();
}

class LiveState extends ChangeNotifier {
  int unread = 0;
  RealtimeState connection = RealtimeState.stopped;
  final notifications = StreamController<Map<String, dynamic>>.broadcast();
  final messages = StreamController<Map<String, dynamic>>.broadcast();
  RealtimeClient? client;

  void setUnread(int value) {
    unread = value;
    notifyListeners();
  }

  void setConnection(RealtimeState value) {
    connection = value;
    notifyListeners();
  }

  @override
  void dispose() {
    notifications.close();
    messages.close();
    super.dispose();
  }
}

class _HomeShellState extends State<HomeShell> with WidgetsBindingObserver {
  int _tab = 0;
  final _live = LiveState();
  final _subscriptions = <StreamSubscription<dynamic>>[];

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    final factory = widget.realtime;
    if (factory != null) {
      final auth = context.read<AuthService>();
      final client = factory();
      _live.client = client;
      _subscriptions
        ..add(client.states.listen(_live.setConnection))
        ..add(client.unreadNotifications.listen(_live.setUnread))
        ..add(
          client.notifications.listen((n) {
            _live.notifications.add(n);
            if (n['is_read'] != true) _live.setUnread(_live.unread + 1);
          }),
        )
        ..add(client.messages.listen(_live.messages.add))
        ..add(client.sessionExpired.listen((_) => auth.expire()));
      client.start();
    }
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    // Back in the foreground: reconnect at once (the resync fetches what was missed).
    final client = _live.client;
    if (state == AppLifecycleState.resumed && client != null && client.state != RealtimeState.online) client.start();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    for (final s in _subscriptions) {
      s.cancel();
    }
    _live.client?.dispose();
    _live.dispose();
    super.dispose();
  }

  void open(int tab) => setState(() => _tab = tab);

  @override
  Widget build(BuildContext context) {
    return ChangeNotifierProvider<LiveState>.value(
      value: _live,
      child: Scaffold(
        body: IndexedStack(
          index: _tab,
          children: [
            DashboardScreen(onOpenTab: open),
            const PlanningScreen(),
            const CommunicationScreen(),
            const ProfileScreen(),
          ],
        ),
        bottomNavigationBar: Consumer<LiveState>(
          builder: (context, live, _) => NavigationBar(
            selectedIndex: _tab,
            onDestinationSelected: open,
            destinations: [
              const NavigationDestination(
                icon: Icon(Icons.home_outlined),
                selectedIcon: Icon(Icons.home),
                label: 'Accueil',
              ),
              const NavigationDestination(
                icon: Icon(Icons.calendar_month_outlined),
                selectedIcon: Icon(Icons.calendar_month),
                label: 'Planning',
              ),
              NavigationDestination(
                icon: Badge(
                  isLabelVisible: live.unread > 0,
                  label: Text('${live.unread}'),
                  child: const Icon(Icons.chat_bubble_outline),
                ),
                selectedIcon: const Icon(Icons.chat_bubble),
                label: 'Messages',
              ),
              const NavigationDestination(
                icon: Icon(Icons.person_outline),
                selectedIcon: Icon(Icons.person),
                label: 'Profil',
              ),
            ],
          ),
        ),
      ),
    );
  }
}
