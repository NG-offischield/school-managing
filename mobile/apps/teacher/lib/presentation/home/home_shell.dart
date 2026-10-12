import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:school_core/school_core.dart';

import '../communication/new_conversation_screen.dart';
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

class _HomeShellState extends State<HomeShell> with WidgetsBindingObserver {
  int _tab = 0;
  final _live = LiveState(); // school_core: shared by every app

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    final factory = widget.realtime;
    if (factory != null) _live.attach(factory(), context.read<AuthService>());
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) _live.resume();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
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
            CommunicationScreen(
              forum: true,
              composeConversation: (context) => openAbove<Conversation>(context, const NewConversationScreen()),
            ),
            const ProfileScreen(),
          ],
        ),
        bottomNavigationBar: Consumer<LiveState>(
          builder: (context, live, _) => NavigationBar(
            selectedIndex: _tab,
            onDestinationSelected: open,
            destinations: [
              NavigationDestination(
                icon: Icon(Icons.home_outlined),
                selectedIcon: Icon(Icons.home),
                label: tr('Accueil'),
              ),
              NavigationDestination(
                icon: Icon(Icons.calendar_month_outlined),
                selectedIcon: Icon(Icons.calendar_month),
                label: tr('Planning'),
              ),
              NavigationDestination(
                icon: Badge(
                  isLabelVisible: live.unread > 0,
                  label: Text('${live.unread}'),
                  child: const Icon(Icons.chat_bubble_outline),
                ),
                selectedIcon: const Icon(Icons.chat_bubble),
                label: tr('Messages'),
              ),
              NavigationDestination(
                icon: Icon(Icons.person_outline),
                selectedIcon: Icon(Icons.person),
                label: tr('Profil'),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
