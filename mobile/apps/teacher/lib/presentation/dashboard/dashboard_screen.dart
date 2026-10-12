import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:school_core/school_core.dart';

import '../../data/teacher_repository.dart';
import '../../models/models.dart';
import '../common.dart';
import '../planning/session_screen.dart';

class DashboardData {
  DashboardData({required this.courses, required this.upcoming, required this.unread, this.pay});

  final List<Course> courses;
  final List<TeachingSession> upcoming; // today -> +14 days, oldest first
  final int unread;
  final PaySummary? pay;
}

/// What the server lets THIS teacher see: identity, today's sessions, next
/// class, own courses, unread notifications, own remuneration (if allowed).
class DashboardScreen extends StatefulWidget {
  const DashboardScreen({super.key, required this.onOpenTab, this.now});

  final void Function(int tab) onOpenTab;
  final DateTime Function()? now;

  @override
  State<DashboardScreen> createState() => _DashboardScreenState();
}

class _DashboardScreenState extends State<DashboardScreen> {
  Future<DashboardData>? _future;

  DateTime get _now => widget.now?.call() ?? DateTime.now();

  @override
  void initState() {
    super.initState();
    _load();
  }

  void _load() {
    final repo = context.read<TeacherRepository>();
    final live = context.read<LiveState>();
    final today = DateTime(_now.year, _now.month, _now.day);
    setState(() {
      _future = () async {
        // Sequential on purpose: a failure (offline...) stops at the first
        // error instead of leaving the others unhandled.
        final courses = await repo.courses();
        final upcoming = await repo.sessions(today, today.add(const Duration(days: 14)));
        final unread = await repo.unreadCount();
        PaySummary? pay;
        try {
          pay = await repo.pay(DateTime(today.year, today.month), DateTime(today.year, today.month + 1, 0));
        } on ApiException {
          pay = null; // remuneration is optional on the dashboard
        }
        live.setUnread(unread);
        return DashboardData(courses: courses, upcoming: upcoming, unread: unread, pay: pay);
      }()..ignore(); // the screen may be gone before an error (expired session)
    });
  }

  @override
  Widget build(BuildContext context) {
    final identity = context.watch<AuthService>().identity!;
    return Scaffold(
      appBar: AppBar(
        title: Text(tr('Accueil')),
        actions: [IconButton(tooltip: tr('Actualiser'), icon: const Icon(Icons.refresh), onPressed: _load)],
      ),
      body: RefreshIndicator(
        onRefresh: () async => _load(),
        child: AsyncBody<DashboardData>(
          future: _future,
          onRetry: _load,
          builder: (context, data) => _content(context, identity, data),
        ),
      ),
    );
  }

  Widget _content(BuildContext context, Identity identity, DashboardData data) {
    final now = _now;
    final today = data.upcoming.where((s) => s.start != null && _sameDay(s.start!, now)).toList();
    final next = data.upcoming.where((s) => !s.cancelled && s.start != null && s.start!.isAfter(now)).firstOrNull;
    final unread = context.watch<LiveState>().unread;
    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 16, 16, 24),
      children: [
        Card(
          color: Tokens.navy,
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Row(
              children: [
                CircleAvatar(
                  radius: 26,
                  backgroundColor: Tokens.primary,
                  child: Text(
                    identity.initials,
                    style: TextStyle(color: Tokens.onPrimary, fontWeight: FontWeight.w700),
                  ),
                ),
                const SizedBox(width: 14),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        tr('Bonjour {0}', [identity.firstName]),
                        style: const TextStyle(color: Colors.white, fontSize: 19, fontWeight: FontWeight.w700),
                      ),
                      Text(identity.current?.schoolName ?? '', style: const TextStyle(color: Colors.white70)),
                      Text(capitalize(dayLong.format(now)), style: const TextStyle(color: Colors.white70)),
                    ],
                  ),
                ),
              ],
            ),
          ),
        ),
        const SizedBox(height: 12),
        Row(
          children: [
            Expanded(
              child: _Metric(
                label: tr('Séances aujourd\'hui'),
                value: '${today.where((s) => !s.cancelled).length}',
                onTap: () => widget.onOpenTab(1),
              ),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: _Metric(label: tr('Notifications non lues'), value: '$unread', onTap: () => widget.onOpenTab(2)),
            ),
          ],
        ),
        SectionTitle(tr('Prochain cours')),
        if (next == null)
          EmptyState(text: tr('Aucun cours prévu dans les 14 prochains jours.'), icon: Icons.event_available_outlined)
        else
          SessionTile(session: next, myName: identity.fullName, showDay: true, onTap: () => _open(next)),
        SectionTitle(
          tr('Aujourd\'hui'),
          trailing: TextButton(onPressed: () => widget.onOpenTab(1), child: Text(tr('Planning'))),
        ),
        if (today.isEmpty)
          EmptyState(text: tr('Aucune séance aujourd\'hui.'), icon: Icons.free_breakfast_outlined)
        else
          ...today.map(
            (s) => Padding(
              padding: const EdgeInsets.only(bottom: 8),
              child: SessionTile(session: s, myName: identity.fullName, onTap: () => _open(s)),
            ),
          ),
        SectionTitle(tr('Mes cours ({0})', [data.courses.length])),
        if (data.courses.isEmpty)
          EmptyState(text: tr('Aucun cours ne vous est attribué.'), icon: Icons.class_outlined)
        else
          Card(
            child: Column(
              children: [
                for (final course in data.courses)
                  ListTile(
                    leading: Icon(Icons.menu_book_outlined, color: Tokens.primary),
                    title: Text(
                      '${course.subjectCode} — ${course.className}',
                      style: const TextStyle(fontWeight: FontWeight.w600),
                    ),
                    subtitle: Text(
                      tr('Coefficient {0}{1}', [
                        course.coefficient,
                        course.weeklyHours.isEmpty ? '' : tr(' · {0} h / semaine', [course.weeklyHours]),
                      ]),
                    ),
                  ),
              ],
            ),
          ),
        if (data.pay != null) ...[
          SectionTitle(tr('Rémunération du mois')),
          Card(
            child: Padding(
              padding: const EdgeInsets.all(14),
              child: Column(
                children: [
                  _payRow(
                    tr('Programmée'),
                    data.pay!.programmed,
                    tr('{0} séance(s)', [data.pay!.sessions['scheduled'] ?? 0]),
                  ),
                  _payRow(
                    tr('Acquise (validée)'),
                    data.pay!.earned,
                    tr('{0} séance(s)', [data.pay!.sessions['validated'] ?? 0]),
                  ),
                  _payRow(tr('Payée'), data.pay!.paid, tr('{0} séance(s)', [data.pay!.sessions['paid'] ?? 0])),
                  const SizedBox(height: 6),
                  Text(
                    tr('Calculée par l\'établissement ; une séance n\'est acquise qu\'après validation.'),
                    style: TextStyle(color: Tokens.textSecondary, fontSize: 12.5),
                  ),
                ],
              ),
            ),
          ),
        ],
      ],
    );
  }

  Widget _payRow(String label, String amount, String detail) => Padding(
    padding: const EdgeInsets.symmetric(vertical: 4),
    child: Row(
      children: [
        Expanded(
          child: Text(label, style: const TextStyle(fontWeight: FontWeight.w600)),
        ),
        Text(formatMoney(amount), style: const TextStyle(fontWeight: FontWeight.w700)),
        const SizedBox(width: 8),
        Text(detail, style: TextStyle(color: Tokens.textSecondary, fontSize: 12.5)),
      ],
    ),
  );

  void _open(TeachingSession session) => Navigator.of(context).push(
    MaterialPageRoute(
      builder: (_) => SessionScreen(sessionId: session.id, preview: session),
    ),
  );

  static bool _sameDay(DateTime a, DateTime b) => a.year == b.year && a.month == b.month && a.day == b.day;
}

class _Metric extends StatelessWidget {
  const _Metric({required this.label, required this.value, this.onTap});

  final String label;
  final String value;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    return Card(
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(10),
        child: Padding(
          padding: const EdgeInsets.all(14),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                value,
                style: TextStyle(fontSize: 28, fontWeight: FontWeight.w800, color: Tokens.navy),
              ),
              Text(label, style: TextStyle(color: Tokens.textSecondary)),
            ],
          ),
        ),
      ),
    );
  }
}
