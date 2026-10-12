import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:school_core/school_core.dart';

import '../data/guardian_repository.dart';
import 'camera/camera_scan_screen.dart';
import 'camera/qr_camera.dart';

/// Signed-in shell of the guardian: Accueil, Portail (scan), Mes passages,
/// Messages, Profil — and the live connection for the whole session.
class HomeShell extends StatefulWidget {
  const HomeShell({super.key, this.realtime, this.camera});

  final RealtimeClient Function()? realtime;
  final QrCamera Function()? camera;

  @override
  State<HomeShell> createState() => _HomeShellState();
}

class _HomeShellState extends State<HomeShell> with WidgetsBindingObserver {
  int _tab = 0;
  final _live = LiveState();
  final _scan = GlobalKey<ScanScreenState>();

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

  /// Accueil -> « Scanner au portail »: the Portail tab, camera open at once.
  void scan() {
    open(1);
    WidgetsBinding.instance.addPostFrameCallback((_) => _scan.currentState?.openCamera());
  }

  @override
  Widget build(BuildContext context) {
    return ChangeNotifierProvider<LiveState>.value(
      value: _live,
      child: Scaffold(
        body: IndexedStack(
          index: _tab,
          children: [
            GuardianHome(onOpenTab: open, onScan: scan),
            ScanScreen(
              key: _scan,
              camera: widget.camera == null ? null : (context) => CameraScanScreen.open(context, widget.camera!),
            ),
            const MyScansScreen(),
            const CommunicationScreen(messaging: false, complaints: false), // spec §8: no messaging for guardians
            const GuardianProfile(),
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
                icon: Icon(Icons.qr_code_scanner),
                selectedIcon: Icon(Icons.qr_code_2),
                label: tr('Portail'),
              ),
              NavigationDestination(
                icon: Icon(Icons.history),
                selectedIcon: Icon(Icons.history_toggle_off),
                label: tr('Passages'),
              ),
              NavigationDestination(
                icon: Badge(
                  isLabelVisible: live.unread > 0,
                  label: Text('${live.unread}'),
                  child: const Icon(Icons.chat_bubble_outline),
                ),
                selectedIcon: const Icon(Icons.chat_bubble),
                label: tr('Alertes'),
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

class _Overview {
  _Overview(this.todayScans, this.notifications, this.breaks);

  final List<ScanRecord> todayScans;
  final List<AppNotification> notifications;
  final List<SchoolBreakItem> breaks;
}

/// Accueil: my passages of the day, what is new, closures to come.
class GuardianHome extends StatefulWidget {
  const GuardianHome({super.key, required this.onOpenTab, this.onScan});

  final void Function(int tab) onOpenTab;

  /// Opens the scanner (camera when available).
  final VoidCallback? onScan;

  @override
  State<GuardianHome> createState() => _GuardianHomeState();
}

class _GuardianHomeState extends State<GuardianHome> {
  Future<_Overview>? _future;
  late final ValueNotifier<int> _scans;

  @override
  void initState() {
    super.initState();
    // Every scan (camera or reader) refreshes the counters of the day.
    _scans = context.read<GuardianRepository>().gate.scans..addListener(_load);
    _load();
  }

  @override
  void dispose() {
    _scans.removeListener(_load);
    super.dispose();
  }

  Future<_Overview> _fetch() async {
    final repo = context.read<GuardianRepository>();
    final scans = await repo.gate.myScans(DateTime.now());
    final notifications = await repo.notifications();
    final breaks = await repo.breaks();
    return _Overview(scans, notifications.take(5).toList(), breaks.take(3).toList());
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
        title: Text(tr('Accueil')),
        actions: [
          const LiveIndicator(),
          IconButton(tooltip: tr('Actualiser'), onPressed: _load, icon: const Icon(Icons.refresh)),
        ],
      ),
      body: AsyncBody<_Overview>(
        future: _future,
        onRetry: _load,
        builder: (context, data) {
          final accepted = data.todayScans.where((s) => acceptedScan(s.result)).length;
          return ListView(
            padding: const EdgeInsets.fromLTRB(16, 8, 16, 24),
            children: [
              Text(
                tr('Bonjour {0}', [auth.identity?.firstName ?? '']),
                style: const TextStyle(fontSize: 22, fontWeight: FontWeight.w800),
              ),
              Text(auth.identity?.current?.schoolName ?? '', style: TextStyle(color: Tokens.textSecondary)),
              const SizedBox(height: 14),
              Card(
                child: ListTile(
                  key: const Key('home.scans'),
                  leading: Icon(Icons.how_to_reg, color: Tokens.primary),
                  title: Text(tr('{0} arrivée(s) enregistrée(s) aujourd\'hui', [accepted])),
                  subtitle: Text(tr('{0} passage(s) au total, par vous', [data.todayScans.length])),
                  trailing: const Icon(Icons.chevron_right),
                  onTap: () => widget.onOpenTab(2),
                ),
              ),
              const SizedBox(height: 8),
              FilledButton.icon(
                key: const Key('home.scan'),
                onPressed: widget.onScan ?? () => widget.onOpenTab(1),
                icon: const Icon(Icons.qr_code_scanner),
                label: Text(tr('Scanner au portail')),
              ),
              if (data.breaks.isNotEmpty) ...[
                _Title(tr('Fermetures à venir')),
                for (final b in data.breaks)
                  Card(
                    child: ListTile(
                      leading: Icon(Icons.event_busy, color: Tokens.warning),
                      title: Text(b.name),
                      subtitle: Text(
                        '${b.typeLabel} · ${b.start == null ? '' : dateOnly.format(b.start!)}'
                        '${b.end == null ? '' : ' → ${dateOnly.format(b.end!)}'}',
                      ),
                    ),
                  ),
              ],
              _Title(tr('Dernières notifications')),
              if (data.notifications.isEmpty)
                Text(tr('Aucune notification.'), style: TextStyle(color: Tokens.textSecondary)),
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

class _Title extends StatelessWidget {
  const _Title(this.text);

  final String text;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.fromLTRB(2, 18, 2, 8),
    child: Text(text, style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w700)),
  );
}

/// Identity, school, logout, about the software.
class GuardianProfile extends StatelessWidget {
  const GuardianProfile({super.key});

  @override
  Widget build(BuildContext context) {
    final auth = context.watch<AuthService>();
    final identity = auth.identity;
    if (identity == null) return const SizedBox.shrink();
    return Scaffold(
      appBar: AppBar(title: Text(tr('Profil'))),
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
                      style: TextStyle(color: Tokens.onPrimary, fontSize: 22, fontWeight: FontWeight.w700),
                    ),
                  ),
                  const SizedBox(height: 10),
                  Text(identity.fullName, style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w700)),
                  Text(identity.username, style: TextStyle(color: Tokens.textSecondary)),
                ],
              ),
            ),
          ),
          Card(
            child: Column(
              children: [
                ListTile(
                  leading: const Icon(Icons.school_outlined),
                  title: Text(tr('Établissement')),
                  subtitle: Text(identity.current?.schoolName ?? '—'),
                ),
                ListTile(
                  leading: Icon(Icons.shield_outlined),
                  title: Text(tr('Rôle')),
                  subtitle: Text(tr('Gardien : contrôle des arrivées au portail')),
                ),
              ],
            ),
          ),
          Card(
            child: ListTile(
              key: const Key('profile.account'),
              leading: const Icon(Icons.manage_accounts_outlined),
              title: Text(tr('Mon compte et paramètres')),
              subtitle: Text(tr('Photo, coordonnées, mot de passe, appareils')),
              trailing: const Icon(Icons.chevron_right),
              onTap: () => Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => const AccountScreen())),
            ),
          ),
          // Server of the school (another network = another address, no rebuild).
          const ServerSettingsTile(),
          const SizedBox(height: 20),
          OutlinedButton.icon(
            key: const Key('profile.logout'),
            style: OutlinedButton.styleFrom(
              foregroundColor: Tokens.error,
              side: BorderSide(color: Tokens.error),
            ),
            onPressed: () => auth.logout(),
            icon: const Icon(Icons.logout),
            label: Text(tr('Se déconnecter')),
          ),
          const SizedBox(height: 28),
          Center(child: SoftwareBrand(size: 18, subtitle: tr('Application gardien · version 0.1.0'))),
        ],
      ),
    );
  }
}
