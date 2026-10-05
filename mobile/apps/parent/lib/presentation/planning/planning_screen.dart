import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:school_core/school_core.dart';

import '../../data/parent_repository.dart';
import '../../models/models.dart';
import '../common.dart';

/// Planning of the selected child's class (existing students/{id}/sessions/):
/// today or the week, subject, teacher, room, and the changes the families
/// must see (cancelled, moved, substitute teacher).
class PlanningScreen extends StatefulWidget {
  const PlanningScreen({super.key});

  @override
  State<PlanningScreen> createState() => _PlanningScreenState();
}

class _PlanningScreenState extends State<PlanningScreen> {
  bool _week = false;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Planning'), actions: const [ChildSwitcher()]),
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
              onSelectionChanged: (value) => setState(() => _week = value.first),
            ),
          ),
          Expanded(
            child: ChildBody(
              builder: (context, child) => _Sessions(key: ValueKey('${child.id}-$_week'), child: child, week: _week),
            ),
          ),
        ],
      ),
    );
  }
}

class _Sessions extends StatefulWidget {
  const _Sessions({super.key, required this.child, required this.week});

  final Child child;
  final bool week;

  @override
  State<_Sessions> createState() => _SessionsState();
}

class _SessionsState extends State<_Sessions> {
  Future<List<ClassSession>>? _future;

  @override
  void initState() {
    super.initState();
    _load();
  }

  void _load() {
    final now = DateTime.now();
    final today = DateTime(now.year, now.month, now.day);
    final from = widget.week ? today.subtract(Duration(days: today.weekday - 1)) : today;
    final to = widget.week ? from.add(const Duration(days: 6)) : today;
    setState(() {
      _future = context.read<ParentRepository>().sessions(widget.child.id, from, to)..ignore();
    });
  }

  @override
  Widget build(BuildContext context) {
    return AsyncBody<List<ClassSession>>(
      future: _future,
      onRetry: _load,
      isEmpty: (rows) => rows.isEmpty,
      emptyText: widget.week ? 'Aucun cours cette semaine.' : 'Aucun cours aujourd\'hui.',
      builder: (context, sessions) {
        final days = <String, List<ClassSession>>{};
        for (final s in sessions) {
          days.putIfAbsent(s.start == null ? '' : capitalize(dayLong.format(s.start!)), () => []).add(s);
        }
        return RefreshIndicator(
          onRefresh: () async {
            _load();
            await _future?.catchError((_) => <ClassSession>[]);
          },
          child: ListView(
            padding: const EdgeInsets.fromLTRB(16, 4, 16, 24),
            children: [
              for (final entry in days.entries) ...[
                if (widget.week) SectionTitle(entry.key),
                for (final s in entry.value) SessionCard(session: s),
              ],
            ],
          ),
        );
      },
    );
  }
}

class SessionCard extends StatelessWidget {
  const SessionCard({super.key, required this.session});

  final ClassSession session;

  @override
  Widget build(BuildContext context) {
    final s = session;
    final room = s.room == null ? 'Salle non attribuée' : 'Salle ${s.room!.label}';
    final notes = <(String, Tone)>[
      if (s.cancelled) ('Cours annulé', Tone.danger),
      if (s.moved && !s.cancelled)
        (
          'Déplacé${s.originalStart == null ? '' : ' (initialement ${dateTime.format(s.originalStart!)})'}',
          Tone.warning,
        ),
      if (s.substituted && !s.cancelled) ('Enseignant remplaçant', Tone.warning),
    ];
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            SizedBox(
              width: 58,
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    s.start == null ? '' : hm.format(s.start!),
                    style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w700),
                  ),
                  Text(s.end == null ? '' : hm.format(s.end!), style: const TextStyle(color: Tokens.textSecondary)),
                ],
              ),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    s.subjectName,
                    style: TextStyle(
                      fontSize: 16,
                      fontWeight: FontWeight.w700,
                      decoration: s.cancelled ? TextDecoration.lineThrough : null,
                    ),
                  ),
                  const SizedBox(height: 2),
                  Text(
                    '${s.teacher.label.isEmpty ? 'Enseignant à confirmer' : s.teacher.label} · $room',
                    style: const TextStyle(color: Tokens.textSecondary),
                  ),
                  Text(s.schoolClass.label, style: const TextStyle(color: Tokens.textSecondary, fontSize: 12.5)),
                  const SizedBox(height: 8),
                  Wrap(
                    spacing: 6,
                    runSpacing: 4,
                    children: [
                      if (notes.isEmpty) StatusChip(s.statusLabel, tone: Tone.info),
                      for (final (label, tone) in notes) StatusChip(label, tone: tone),
                    ],
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}
