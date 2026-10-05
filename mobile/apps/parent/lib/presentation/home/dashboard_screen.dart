import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:school_core/school_core.dart';

import '../../data/parent_repository.dart';
import '../../models/models.dart';
import '../children/link_requests_screen.dart';
import '../common.dart';
import '../documents/documents_screen.dart';
import '../profile/profile_screen.dart';
import 'home_shell.dart';

/// Accueil: the children the server lets me see (class, year, schooling),
/// what is new (notifications, convocations) and the main shortcuts.
class DashboardScreen extends StatefulWidget {
  const DashboardScreen({super.key, required this.onOpenTab});

  final void Function(int tab) onOpenTab;

  @override
  State<DashboardScreen> createState() => _DashboardScreenState();
}

class _Overview {
  _Overview(this.notifications, this.convocations);

  final List<AppNotification> notifications;
  final List<Convocation> convocations;
}

class _DashboardScreenState extends State<DashboardScreen> {
  Future<_Overview>? _future;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<_Overview> _fetch() async {
    final repo = context.read<ParentRepository>();
    // Sequential: one failure is reported once, no orphan request.
    final notifications = await repo.notifications();
    final convocations = await repo.convocations();
    return _Overview(notifications.take(5).toList(), convocations.where((c) => c.status == 'SCHEDULED').toList());
  }

  void _load() => setState(() {
    _future = _fetch()..ignore();
  });

  Future<void> _refresh() async {
    await context.read<ChildScope>().load();
    _load();
    await _future?.catchError((_) => _Overview(const [], const []));
  }

  void _push(Widget screen) => openScreen<void>(context, screen);

  @override
  Widget build(BuildContext context) {
    final auth = context.watch<AuthService>();
    final scope = context.watch<ChildScope>();
    final live = context.watch<LiveState>();
    return Scaffold(
      appBar: AppBar(
        title: const Text('Accueil'),
        actions: [
          if (live.client != null)
            Padding(
              padding: const EdgeInsets.only(right: 4),
              child: Tooltip(
                message: live.connection == RealtimeState.online ? 'Connecté en direct' : 'Hors ligne / reconnexion',
                child: Icon(
                  live.connection == RealtimeState.online ? Icons.cloud_done_outlined : Icons.cloud_off_outlined,
                  color: live.connection == RealtimeState.online ? Tokens.success : Tokens.textSecondary,
                ),
              ),
            ),
          IconButton(
            key: const Key('home.profile'),
            tooltip: 'Mon profil',
            onPressed: () => _push(const ProfileScreen()),
            icon: CircleAvatar(
              radius: 15,
              backgroundColor: Tokens.primarySoft,
              child: Text(
                auth.identity?.initials ?? '?',
                style: const TextStyle(fontSize: 12, color: Tokens.primaryDark, fontWeight: FontWeight.w700),
              ),
            ),
          ),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: _refresh,
        child: ListView(
          padding: const EdgeInsets.fromLTRB(16, 8, 16, 24),
          children: [
            Text(
              'Bonjour ${auth.identity?.firstName ?? ''}',
              style: const TextStyle(fontSize: 22, fontWeight: FontWeight.w800),
            ),
            Text(auth.identity?.current?.schoolName ?? '', style: const TextStyle(color: Tokens.textSecondary)),
            SectionTitle(
              scope.children.length > 1 ? 'Mes enfants (${scope.children.length})' : 'Mon enfant',
              trailing: TextButton(
                key: const Key('home.link'),
                onPressed: () async {
                  await openScreen<void>(context, const LinkRequestsScreen());
                  if (context.mounted) await context.read<ChildScope>().load();
                },
                child: const Text('Rattacher'),
              ),
            ),
            ..._children(scope),
            SectionTitle(
              'Dernières notifications',
              trailing: TextButton(onPressed: () => widget.onOpenTab(4), child: const Text('Tout voir')),
            ),
            AsyncBody<_Overview>(
              future: _future,
              onRetry: _load,
              builder: (context, data) => Column(
                children: [
                  if (data.convocations.isNotEmpty)
                    for (final c in data.convocations)
                      Card(
                        color: Tokens.warningBg,
                        child: ListTile(
                          leading: const Icon(Icons.event_note, color: Tokens.warning),
                          title: Text('Convocation · ${c.start == null ? '' : dateTime.format(c.start!)}'),
                          subtitle: Text(c.reason),
                        ),
                      ),
                  if (data.notifications.isEmpty)
                    const Padding(
                      padding: EdgeInsets.all(12),
                      child: Text('Aucune notification.', style: TextStyle(color: Tokens.textSecondary)),
                    ),
                  for (final n in data.notifications)
                    Card(
                      child: ListTile(
                        leading: Icon(
                          n.read ? Icons.notifications_none : Icons.notifications_active,
                          color: n.read ? Tokens.textSecondary : Tokens.primary,
                        ),
                        title: Text(n.title, style: TextStyle(fontWeight: n.read ? FontWeight.w500 : FontWeight.w700)),
                        subtitle: Text('${n.typeLabel} · ${n.at == null ? '' : dateTime.format(n.at!)}'),
                      ),
                    ),
                ],
              ),
            ),
            const SectionTitle('Raccourcis'),
            Wrap(
              spacing: 10,
              runSpacing: 10,
              children: [
                _Shortcut(
                  key: const Key('home.documents'),
                  icon: Icons.description_outlined,
                  label: 'Bulletins et documents',
                  onTap: () => _push(const DocumentsScreen()),
                ),
                _Shortcut(icon: Icons.fact_check_outlined, label: 'Présences', onTap: () => widget.onOpenTab(1)),
                _Shortcut(
                  icon: Icons.calendar_month_outlined,
                  label: 'Emploi du temps',
                  onTap: () => widget.onOpenTab(2),
                ),
                _Shortcut(
                  icon: Icons.account_balance_wallet_outlined,
                  label: 'Scolarité et paiements',
                  onTap: () => widget.onOpenTab(3),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  List<Widget> _children(ChildScope scope) {
    if (!scope.loaded) {
      return const [
        Padding(
          padding: EdgeInsets.all(16),
          child: Center(child: CircularProgressIndicator(semanticsLabel: 'Chargement')),
        ),
      ];
    }
    final error = scope.error;
    if (error != null) {
      return [MessageBanner(error is ApiException ? error.userMessage : 'Impossible de charger vos enfants.')];
    }
    if (scope.children.isEmpty) {
      return [
        const Card(
          child: Padding(
            padding: EdgeInsets.all(16),
            child: Text(
              'Aucun enfant rattaché. Demandez le rattachement de votre enfant : l\'établissement vérifiera votre '
              'pièce d\'identité, puis vous verrez sa scolarité ici.',
            ),
          ),
        ),
      ];
    }
    return [
      for (final child in scope.children)
        Card(
          shape: child.id == scope.selected?.id
              ? RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(10),
                  side: const BorderSide(color: Tokens.primary, width: 1.5),
                )
              : null,
          child: ListTile(
            key: Key('child.${child.id}'),
            onTap: () => scope.select(child),
            leading: CircleAvatar(
              backgroundColor: Tokens.primarySoft,
              child: Text(
                child.firstName.isEmpty ? '?' : child.firstName[0],
                style: const TextStyle(color: Tokens.primaryDark, fontWeight: FontWeight.w700),
              ),
            ),
            title: Text(child.name, style: const TextStyle(fontWeight: FontWeight.w700)),
            subtitle: Text(child.schooling),
            trailing: child.id == scope.selected?.id
                ? const Icon(Icons.check_circle, color: Tokens.primary, semanticLabel: 'Enfant sélectionné')
                : null,
          ),
        ),
    ];
  }
}

class _Shortcut extends StatelessWidget {
  const _Shortcut({super.key, required this.icon, required this.label, required this.onTap});

  final IconData icon;
  final String label;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final width = (MediaQuery.sizeOf(context).width - 42) / 2;
    return SizedBox(
      width: width,
      child: Card(
        margin: EdgeInsets.zero,
        child: InkWell(
          borderRadius: BorderRadius.circular(10),
          onTap: onTap,
          child: Padding(
            padding: const EdgeInsets.all(14),
            child: Row(
              children: [
                Icon(icon, color: Tokens.primary),
                const SizedBox(width: 10),
                Expanded(
                  child: Text(label, style: const TextStyle(fontWeight: FontWeight.w600)),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
