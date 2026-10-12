import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:school_core/school_core.dart';

import '../../data/teacher_repository.dart';
import '../../models/models.dart';
import '../common.dart';
import 'session_screen.dart';

enum PlanningView { today, week }

/// The teacher's sessions (taught or planned, substitutions included), from
/// GET /teacher/sessions/ — the existing planning API.
class PlanningScreen extends StatefulWidget {
  const PlanningScreen({super.key, this.now});

  final DateTime Function()? now;

  @override
  State<PlanningScreen> createState() => _PlanningScreenState();
}

class _PlanningScreenState extends State<PlanningScreen> {
  PlanningView _view = PlanningView.today;
  late DateTime _monday;
  Future<List<TeachingSession>>? _future;

  DateTime get _today {
    final now = widget.now?.call() ?? DateTime.now();
    return DateTime(now.year, now.month, now.day);
  }

  @override
  void initState() {
    super.initState();
    _monday = _today.subtract(Duration(days: _today.weekday - 1));
    _load();
  }

  void _load() {
    final repo = context.read<TeacherRepository>();
    setState(() {
      _future =
          (_view == PlanningView.today
                ? repo.sessions(_today, _today)
                : repo.sessions(_monday, _monday.add(const Duration(days: 6))))
            ..ignore();
    });
  }

  void _shift(int days) {
    _monday = _monday.add(Duration(days: days));
    _load();
  }

  @override
  Widget build(BuildContext context) {
    final myName = context.watch<AuthService>().identity?.fullName ?? '';
    final weekLabel = tr('Semaine du {0} au {1}', [
      dayShort.format(_monday),
      dayShort.format(_monday.add(const Duration(days: 6))),
    ]);
    return Scaffold(
      appBar: AppBar(
        title: Text(tr('Planning')),
        actions: [IconButton(tooltip: tr('Actualiser'), icon: const Icon(Icons.refresh), onPressed: _load)],
      ),
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 12, 16, 4),
            child: SegmentedButton<PlanningView>(
              segments: [
                ButtonSegment(value: PlanningView.today, label: Text(tr('Aujourd\'hui')), icon: Icon(Icons.today)),
                ButtonSegment(
                  value: PlanningView.week,
                  label: Text(tr('Semaine')),
                  icon: Icon(Icons.view_week_outlined),
                ),
              ],
              selected: {_view},
              onSelectionChanged: (value) {
                _view = value.first;
                _load();
              },
            ),
          ),
          if (_view == PlanningView.week)
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 8),
              child: Row(
                children: [
                  IconButton(
                    tooltip: tr('Semaine précédente'),
                    icon: const Icon(Icons.chevron_left),
                    onPressed: () => _shift(-7),
                  ),
                  Expanded(
                    child: Text(
                      capitalize(weekLabel),
                      textAlign: TextAlign.center,
                      style: const TextStyle(fontWeight: FontWeight.w600),
                    ),
                  ),
                  IconButton(
                    tooltip: tr('Semaine suivante'),
                    icon: const Icon(Icons.chevron_right),
                    onPressed: () => _shift(7),
                  ),
                ],
              ),
            ),
          Expanded(
            child: RefreshIndicator(
              onRefresh: () async => _load(),
              child: AsyncBody<List<TeachingSession>>(
                future: _future,
                onRetry: _load,
                isEmpty: (rows) => rows.isEmpty,
                emptyText: _view == PlanningView.today
                    ? tr('Aucune séance aujourd\'hui.')
                    : tr('Aucune séance cette semaine.'),
                builder: (context, rows) => _list(rows, myName),
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _list(List<TeachingSession> rows, String myName) {
    final children = <Widget>[];
    DateTime? day;
    for (final session in rows) {
      final start = session.start;
      if (_view == PlanningView.week && start != null && (day == null || !_sameDay(day, start))) {
        day = start;
        children.add(SectionTitle(capitalize(dayLong.format(start))));
      }
      children.add(
        Padding(
          padding: const EdgeInsets.only(bottom: 8),
          child: SessionTile(
            session: session,
            myName: myName,
            onTap: () => Navigator.of(context).push(
              MaterialPageRoute(
                builder: (_) => SessionScreen(sessionId: session.id, preview: session),
              ),
            ),
          ),
        ),
      );
    }
    return ListView(padding: const EdgeInsets.fromLTRB(16, 8, 16, 24), children: children);
  }

  static bool _sameDay(DateTime a, DateTime b) => a.year == b.year && a.month == b.month && a.day == b.day;
}
