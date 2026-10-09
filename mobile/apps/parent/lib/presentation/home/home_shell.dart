import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:school_core/school_core.dart';

import '../../data/parent_repository.dart';
import '../attendance/attendance_screen.dart';
import '../common.dart';
import '../communication/new_message_screens.dart';
import '../finance/finance_screen.dart';
import '../planning/planning_screen.dart';
import 'dashboard_screen.dart';

/// Signed-in shell: 5 tabs (Accueil, Présences, Planning, Finance, Messages),
/// the children the server lets this parent see (ChildScope) and the live
/// connection (existing ws/v1/realtime/) for the whole session.
class HomeShell extends StatefulWidget {
  const HomeShell({super.key, this.realtime});

  final RealtimeClient Function()? realtime;

  @override
  State<HomeShell> createState() => _HomeShellState();
}

class _HomeShellState extends State<HomeShell> with WidgetsBindingObserver {
  int _tab = 0;
  final _live = LiveState(); // school_core: shared by every app
  late final ChildScope _children;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _children = ChildScope(context.read<ParentRepository>())..load();
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
    _children.dispose();
    super.dispose();
  }

  void open(int tab) => setState(() => _tab = tab);

  @override
  Widget build(BuildContext context) {
    return MultiProvider(
      providers: [
        ChangeNotifierProvider<LiveState>.value(value: _live),
        ChangeNotifierProvider<ChildScope>.value(value: _children),
      ],
      child: Scaffold(
        body: IndexedStack(
          index: _tab,
          children: [
            DashboardScreen(onOpenTab: open),
            const AttendanceScreen(),
            const PlanningScreen(),
            const FinanceScreen(),
            CommunicationScreen(
              forum: true, // the school forum (server-side membership; guardians excluded)
              composeConversation: (context) => openScreen<Conversation>(context, const NewConversationScreen()),
              composeComplaint: (context) {
                final child = context.read<ChildScope>().selected;
                return openScreen<Complaint>(
                  context,
                  ComplaintComposer(studentId: child?.id, studentLabel: child?.name),
                );
              },
            ),
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
                icon: Icon(Icons.fact_check_outlined),
                selectedIcon: Icon(Icons.fact_check),
                label: 'Présences',
              ),
              const NavigationDestination(
                icon: Icon(Icons.calendar_month_outlined),
                selectedIcon: Icon(Icons.calendar_month),
                label: 'Planning',
              ),
              const NavigationDestination(
                icon: Icon(Icons.account_balance_wallet_outlined),
                selectedIcon: Icon(Icons.account_balance_wallet),
                label: 'Finance',
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
            ],
          ),
        ),
      ),
    );
  }
}
