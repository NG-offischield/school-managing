import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:school_core/school_core.dart';

import '../data/staff_repository.dart';

/// Signed-in shell of the staff: Accueil, Planning, Portail (scan),
/// Messages, Profil (functions, my passages, my remuneration) — and the live
/// connection for the whole session.
class HomeShell extends StatefulWidget {
  const HomeShell({super.key, this.realtime});

  final RealtimeClient Function()? realtime;

  @override
  State<HomeShell> createState() => _HomeShellState();
}

class _HomeShellState extends State<HomeShell> with WidgetsBindingObserver {
  int _tab = 0;
  final _live = LiveState();

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
            StaffHome(onOpenTab: open),
            const StaffPlanning(),
            const ScanScreen(),
            const CommunicationScreen(complaints: false, forum: true), // complaints: parents and teachers only
            const StaffProfile(),
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
              const NavigationDestination(
                icon: Icon(Icons.qr_code_scanner),
                selectedIcon: Icon(Icons.qr_code_2),
                label: 'Portail',
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

class _Title extends StatelessWidget {
  const _Title(this.text);

  final String text;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.fromLTRB(2, 18, 2, 8),
    child: Text(text, style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w700)),
  );
}

class _Overview {
  _Overview(this.me, this.today, this.notifications, this.breaks);

  final StaffMe? me;
  final List<SchoolSession> today;
  final List<AppNotification> notifications;
  final List<SchoolBreakItem> breaks;
}

/// Accueil: my functions, the school's day, what is new, closures.
class StaffHome extends StatefulWidget {
  const StaffHome({super.key, required this.onOpenTab});

  final void Function(int tab) onOpenTab;

  @override
  State<StaffHome> createState() => _StaffHomeState();
}

class _StaffHomeState extends State<StaffHome> {
  Future<_Overview>? _future;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<_Overview> _fetch() async {
    final repo = context.read<StaffRepository>();
    final now = DateTime.now();
    final today = DateTime(now.year, now.month, now.day);
    final me = await repo.me();
    final sessions = await repo.sessions(today, today);
    final notifications = await repo.notifications();
    final breaks = await repo.breaks();
    return _Overview(me, sessions, notifications.take(5).toList(), breaks.take(3).toList());
  }

  void _load() {
    setState(() {
      _future = _fetch()..ignore();
    });
  }

  @override
  Widget build(BuildContext context) {
    final auth = context.watch<AuthService>();
    return Scaffold(
      appBar: AppBar(
        title: const Text('Accueil'),
        actions: [
          const LiveIndicator(),
          IconButton(tooltip: 'Actualiser', onPressed: _load, icon: const Icon(Icons.refresh)),
        ],
      ),
      body: AsyncBody<_Overview>(
        future: _future,
        onRetry: _load,
        builder: (context, data) {
          final cancelled = data.today.where((s) => s.cancelled).length;
          return ListView(
            padding: const EdgeInsets.fromLTRB(16, 8, 16, 24),
            children: [
              Text(
                'Bonjour ${auth.identity?.firstName ?? ''}',
                style: const TextStyle(fontSize: 22, fontWeight: FontWeight.w800),
              ),
              Text(auth.identity?.current?.schoolName ?? '', style: const TextStyle(color: Tokens.textSecondary)),
              const _Title('Mes fonctions'),
              if (data.me == null || data.me!.functions.isEmpty)
                const Text('Aucune fonction attribuée.', style: TextStyle(color: Tokens.textSecondary))
              else
                Wrap(
                  spacing: 6,
                  runSpacing: 6,
                  children: [for (final f in data.me!.functions) StatusChip(f.label, tone: Tone.info)],
                ),
              const _Title('Aujourd\'hui dans l\'établissement'),
              Card(
                child: ListTile(
                  key: const Key('home.today'),
                  leading: const Icon(Icons.calendar_today, color: Tokens.primary),
                  title: Text('${data.today.length} séance(s) au planning'),
                  subtitle: Text(cancelled == 0 ? 'Aucune annulation' : '$cancelled annulation(s)'),
                  trailing: const Icon(Icons.chevron_right),
                  onTap: () => widget.onOpenTab(1),
                ),
              ),
              if (data.breaks.isNotEmpty) ...[
                const _Title('Fermetures à venir'),
                for (final b in data.breaks)
                  Card(
                    child: ListTile(
                      leading: const Icon(Icons.event_busy, color: Tokens.warning),
                      title: Text(b.name),
                      subtitle: Text(
                        '${b.typeLabel} · ${b.start == null ? '' : dateOnly.format(b.start!)}'
                        '${b.end == null ? '' : ' → ${dateOnly.format(b.end!)}'}',
                      ),
                    ),
                  ),
              ],
              const _Title('Dernières notifications'),
              if (data.notifications.isEmpty)
                const Text('Aucune notification.', style: TextStyle(color: Tokens.textSecondary)),
              for (final n in data.notifications)
                Card(
                  child: ListTile(
                    leading: Icon(
                      n.read ? Icons.notifications_none : Icons.notifications_active,
                      color: n.read ? Tokens.textSecondary : Tokens.primary,
                    ),
                    title: Text(n.title, style: TextStyle(fontWeight: n.read ? FontWeight.w500 : FontWeight.w700)),
                    subtitle: Text('${n.typeLabel}${n.at == null ? '' : ' · ${dateTime.format(n.at!)}'}'),
                    onTap: () => widget.onOpenTab(3),
                  ),
                ),
            ],
          );
        },
      ),
    );
  }
}

/// The school's planning (today or the week) and its recent changes.
class StaffPlanning extends StatefulWidget {
  const StaffPlanning({super.key});

  @override
  State<StaffPlanning> createState() => _StaffPlanningState();
}

class _PlanningData {
  _PlanningData(this.sessions, this.changes);

  final List<SchoolSession> sessions;
  final List<PlanningChange> changes;
}

class _StaffPlanningState extends State<StaffPlanning> {
  bool _week = false;
  Future<_PlanningData>? _future;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<_PlanningData> _fetch() async {
    final repo = context.read<StaffRepository>();
    final now = DateTime.now();
    final today = DateTime(now.year, now.month, now.day);
    final from = _week ? today.subtract(Duration(days: today.weekday - 1)) : today;
    final to = _week ? from.add(const Duration(days: 6)) : today;
    final sessions = await repo.sessions(from, to);
    final changes = await repo.changes(since: today.subtract(const Duration(days: 7)));
    return _PlanningData(sessions, changes);
  }

  void _load() {
    setState(() {
      _future = _fetch()..ignore();
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Planning'), actions: const [LiveIndicator()]),
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 8, 16, 4),
            child: SegmentedButton<bool>(
              segments: const [
                ButtonSegment(value: false, label: Text('Aujourd\'hui'), icon: Icon(Icons.today)),
                ButtonSegment(value: true, label: Text('Semaine'), icon: Icon(Icons.view_week)),
              ],
              selected: {_week},
              onSelectionChanged: (value) {
                _week = value.first;
                _load();
              },
            ),
          ),
          Expanded(
            child: AsyncBody<_PlanningData>(
              future: _future,
              onRetry: _load,
              builder: (context, data) {
                final days = <String, List<SchoolSession>>{};
                for (final s in data.sessions) {
                  days.putIfAbsent(s.start == null ? '' : capitalize(dayLong.format(s.start!)), () => []).add(s);
                }
                return ListView(
                  padding: const EdgeInsets.fromLTRB(16, 4, 16, 24),
                  children: [
                    if (data.sessions.isEmpty)
                      const Padding(
                        padding: EdgeInsets.all(12),
                        child: Text('Aucune séance.', style: TextStyle(color: Tokens.textSecondary)),
                      ),
                    for (final entry in days.entries) ...[
                      if (_week) _Title(entry.key),
                      for (final s in entry.value) _SessionTile(session: s),
                    ],
                    if (data.changes.isNotEmpty) ...[
                      const _Title('Changements récents'),
                      for (final c in data.changes)
                        Card(
                          child: ListTile(
                            leading: const Icon(Icons.change_circle_outlined, color: Tokens.warning),
                            title: Text(c.typeLabel),
                            subtitle: Text(
                              [
                                if (c.date != null) 'Séance du ${c.date}',
                                if ((c.reason ?? '').isNotEmpty) c.reason!,
                                if (c.at != null) 'le ${dateTime.format(c.at!)}',
                              ].join(' · '),
                            ),
                          ),
                        ),
                    ],
                  ],
                );
              },
            ),
          ),
        ],
      ),
    );
  }
}

class _SessionTile extends StatelessWidget {
  const _SessionTile({required this.session});

  final SchoolSession session;

  @override
  Widget build(BuildContext context) {
    final s = session;
    final room = s.room == null ? 'Salle non attribuée' : 'Salle ${s.room!.label}';
    return Card(
      child: ListTile(
        leading: SizedBox(
          width: 52,
          child: Text(
            s.start == null ? '' : hm.format(s.start!),
            style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700),
          ),
        ),
        title: Text(
          '${s.schoolClass.label} · ${s.subjectName}',
          style: TextStyle(fontWeight: FontWeight.w600, decoration: s.cancelled ? TextDecoration.lineThrough : null),
        ),
        subtitle: Text('${s.teacher.label} · $room'),
        trailing: StatusChip(
          s.cancelled ? 'Annulée' : (s.substituted ? 'Remplacement' : (s.moved ? 'Déplacée' : s.statusLabel)),
          tone: s.cancelled ? Tone.danger : (s.substituted || s.moved ? Tone.warning : Tone.info),
        ),
      ),
    );
  }
}

/// Identity, functions, attendance (no API yet), my passages, my
/// remuneration, logout.
class StaffProfile extends StatefulWidget {
  const StaffProfile({super.key});

  @override
  State<StaffProfile> createState() => _StaffProfileState();
}

class _StaffProfileState extends State<StaffProfile> {
  Future<StaffMe?>? _future;

  @override
  void initState() {
    super.initState();
    _future = context.read<StaffRepository>().me()..ignore();
  }

  @override
  Widget build(BuildContext context) {
    final auth = context.watch<AuthService>();
    final identity = auth.identity;
    if (identity == null) return const SizedBox.shrink();
    return Scaffold(
      appBar: AppBar(title: const Text('Profil')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                children: [
                  CircleAvatar(
                    radius: 34,
                    backgroundColor: Tokens.primary,
                    child: Text(
                      identity.initials,
                      style: const TextStyle(color: Colors.white, fontSize: 22, fontWeight: FontWeight.w700),
                    ),
                  ),
                  const SizedBox(height: 10),
                  Text(identity.fullName, style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w700)),
                  Text(identity.username, style: const TextStyle(color: Tokens.textSecondary)),
                  FutureBuilder<StaffMe?>(
                    future: _future,
                    builder: (context, snapshot) {
                      final me = snapshot.data;
                      if (me == null) return const SizedBox.shrink();
                      return Padding(
                        padding: const EdgeInsets.only(top: 6),
                        child: Text(
                          'Matricule ${me.employeeNumber} · ${me.functions.map((f) => f.label).join(', ')}',
                          textAlign: TextAlign.center,
                        ),
                      );
                    },
                  ),
                ],
              ),
            ),
          ),
          Card(
            child: Column(
              children: [
                ListTile(
                  leading: const Icon(Icons.school_outlined),
                  title: const Text('Établissement'),
                  subtitle: Text(identity.current?.schoolName ?? '—'),
                ),
                ListTile(
                  key: const Key('profile.scans'),
                  leading: const Icon(Icons.history),
                  title: const Text('Mes passages enregistrés'),
                  trailing: const Icon(Icons.chevron_right),
                  onTap: () => openAbove<void>(context, const MyScansScreen()),
                ),
                ListTile(
                  key: const Key('profile.pay'),
                  leading: const Icon(Icons.payments_outlined),
                  title: const Text('Ma rémunération'),
                  trailing: const Icon(Icons.chevron_right),
                  onTap: () => openAbove<void>(context, const PayslipsScreen()),
                ),
                const ListTile(
                  leading: Icon(Icons.badge_outlined),
                  title: Text('Présence du personnel'),
                  subtitle: Text('Pas encore disponible : l\'établissement ne la suit pas dans l\'application.'),
                ),
              ],
            ),
          ),
          // Server of the school (another network = another address, no rebuild).
          const ServerSettingsTile(),
          const SizedBox(height: 20),
          OutlinedButton.icon(
            key: const Key('profile.logout'),
            style: OutlinedButton.styleFrom(
              foregroundColor: Tokens.error,
              side: const BorderSide(color: Tokens.error),
            ),
            onPressed: () => auth.logout(),
            icon: const Icon(Icons.logout),
            label: const Text('Se déconnecter'),
          ),
          const SizedBox(height: 28),
          const Center(child: SoftwareBrand(size: 18, subtitle: 'Application personnel · version 0.1.0')),
        ],
      ),
    );
  }
}

/// MY approved / paid payrolls (the server never lists another person's).
class PayslipsScreen extends StatefulWidget {
  const PayslipsScreen({super.key});

  @override
  State<PayslipsScreen> createState() => _PayslipsScreenState();
}

class _PayslipsScreenState extends State<PayslipsScreen> {
  Future<List<Payslip>>? _future;

  @override
  void initState() {
    super.initState();
    _load();
  }

  void _load() {
    setState(() {
      _future = context.read<StaffRepository>().payslips()..ignore();
    });
  }

  Future<void> _open(Payslip p) async {
    final repo = context.read<StaffRepository>();
    try {
      final detail = await repo.payslip(p.id);
      if (!mounted) return;
      await showModalBottomSheet<void>(
        context: context,
        showDragHandle: true,
        builder: (_) => Padding(
          padding: const EdgeInsets.fromLTRB(20, 0, 20, 28),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(detail.period, style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w700)),
              const SizedBox(height: 8),
              for (final line in detail.lines)
                _Row(lineKinds[line.id] ?? line.id, formatMoney(line.label, detail.currency)),
              const Divider(),
              _Row('Net à payer', formatMoney(detail.payable, detail.currency), strong: true),
            ],
          ),
        ),
      );
    } on ApiException catch (error) {
      if (mounted) showMessage(context, error.userMessage);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Ma rémunération')),
      body: AsyncBody<List<Payslip>>(
        future: _future,
        onRetry: _load,
        isEmpty: (rows) => rows.isEmpty,
        emptyText: 'Aucune paie validée pour le moment.',
        builder: (context, rows) => ListView(
          padding: const EdgeInsets.all(12),
          children: [
            for (final p in rows)
              Card(
                child: ListTile(
                  key: Key('payslip.${p.id}'),
                  title: Text(p.period, style: const TextStyle(fontWeight: FontWeight.w700)),
                  subtitle: Text(p.paidAt == null ? p.statusLabel : 'Payée le ${dateOnly.format(p.paidAt!)}'),
                  trailing: Text(
                    formatMoney(p.payable, p.currency),
                    style: const TextStyle(fontWeight: FontWeight.w700),
                  ),
                  onTap: () => _open(p),
                ),
              ),
          ],
        ),
      ),
    );
  }
}

class _Row extends StatelessWidget {
  const _Row(this.label, this.value, {this.strong = false});

  final String label;
  final String value;
  final bool strong;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.symmetric(vertical: 4),
    child: Row(
      children: [
        Expanded(child: Text(label)),
        Text(value, style: TextStyle(fontWeight: strong ? FontWeight.w700 : FontWeight.w500)),
      ],
    ),
  );
}
