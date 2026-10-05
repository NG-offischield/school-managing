import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:school_core/school_core.dart';

import '../../data/teacher_repository.dart';
import '../../models/models.dart';
import '../common.dart';

/// One session: details, changes concerning it, and the self-declared
/// presence (existing endpoint POST /teacher/sessions/{id}/check-in/; the
/// administration validates it — no attendance engine on the phone).
class SessionScreen extends StatefulWidget {
  const SessionScreen({super.key, required this.sessionId, this.preview});

  final String sessionId;
  final TeachingSession? preview;

  @override
  State<SessionScreen> createState() => _SessionScreenState();
}

class _SessionScreenState extends State<SessionScreen> {
  Future<(TeachingSession, List<ScheduleChangeItem>)>? _future;
  String? _message;
  Tone _tone = Tone.success;
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  void _load() {
    final repo = context.read<TeacherRepository>();
    setState(() {
      _future = () async {
        final session = await repo.session(widget.sessionId);
        List<ScheduleChangeItem> changes;
        try {
          changes = await repo.changes(widget.sessionId);
        } on ApiException {
          changes = const [];
        }
        return (session, changes);
      }()..ignore();
    });
  }

  Future<void> _checkIn(String status) async {
    setState(() {
      _busy = true;
      _message = null;
    });
    try {
      await context.read<TeacherRepository>().checkIn(widget.sessionId, status);
      _tone = Tone.success;
      _message = status == 'PRESENT'
          ? 'Présence déclarée. L\'administration la validera.'
          : 'Absence déclarée. L\'administration en est informée.';
    } on ApiException catch (error) {
      _tone = Tone.warning;
      _message = error.userMessage;
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final myName = context.watch<AuthService>().identity?.fullName ?? '';
    return Scaffold(
      appBar: AppBar(title: Text(widget.preview?.title ?? 'Séance')),
      body: AsyncBody<(TeachingSession, List<ScheduleChangeItem>)>(
        future: _future,
        onRetry: _load,
        builder: (context, data) {
          final (session, changes) = data;
          final note = substitutionNote(session, myName);
          return ListView(
            padding: const EdgeInsets.all(16),
            children: [
              if (_message != null) ...[MessageBanner(_message!, tone: _tone), const SizedBox(height: 12)],
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(16),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(session.title, style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w800)),
                      const SizedBox(height: 4),
                      Text(session.subject.extra, style: const TextStyle(color: Tokens.textSecondary)),
                      const SizedBox(height: 12),
                      StatusChip(session.statusLabel, tone: sessionTone(session)),
                      const Divider(height: 28),
                      _row(
                        Icons.event_outlined,
                        'Date',
                        session.start == null ? '—' : capitalize(dayLong.format(session.start!)),
                      ),
                      _row(Icons.schedule, 'Horaire', hours(session)),
                      _row(Icons.groups_outlined, 'Classe', session.schoolClass.label),
                      _row(
                        Icons.meeting_room_outlined,
                        'Salle',
                        session.room == null ? 'Non attribuée' : '${session.room!.label} — ${session.room!.extra}',
                      ),
                      _row(Icons.person_outline, 'Enseignant', session.teacher.label),
                      if (note != null) _row(Icons.swap_horiz, 'Remplacement', note),
                    ],
                  ),
                ),
              ),
              if (!session.cancelled) ...[
                const SectionTitle('Ma présence'),
                const Text(
                  'Déclarez votre présence une fois la séance commencée. Elle sera validée par l\'administration.',
                  style: TextStyle(color: Tokens.textSecondary),
                ),
                const SizedBox(height: 10),
                Row(
                  children: [
                    Expanded(
                      child: FilledButton.icon(
                        key: const Key('session.present'),
                        onPressed: _busy ? null : () => _checkIn('PRESENT'),
                        icon: const Icon(Icons.check),
                        label: const Text('Présent'),
                      ),
                    ),
                    const SizedBox(width: 10),
                    Expanded(
                      child: OutlinedButton.icon(
                        key: const Key('session.absent'),
                        onPressed: _busy ? null : () => _checkIn('ABSENT'),
                        icon: const Icon(Icons.close),
                        label: const Text('Absent'),
                      ),
                    ),
                  ],
                ),
              ],
              SectionTitle('Changements (${changes.length})'),
              if (changes.isEmpty)
                const Text('Aucun changement pour cette séance.', style: TextStyle(color: Tokens.textSecondary))
              else
                Card(
                  child: Column(
                    children: [
                      for (final change in changes)
                        ListTile(
                          leading: const Icon(Icons.history, color: Tokens.primary),
                          title: Text(change.label),
                          subtitle: Text(
                            [
                              if (change.at != null) dateTime.format(change.at!),
                              if (change.reason.isNotEmpty) change.reason,
                            ].join(' · '),
                          ),
                        ),
                    ],
                  ),
                ),
            ],
          );
        },
      ),
    );
  }

  Widget _row(IconData icon, String label, String value) => Padding(
    padding: const EdgeInsets.symmetric(vertical: 6),
    child: Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Icon(icon, size: 20, color: Tokens.primary),
        const SizedBox(width: 10),
        SizedBox(
          width: 108,
          child: Text(label, style: const TextStyle(color: Tokens.textSecondary)),
        ),
        Expanded(
          child: Text(value, style: const TextStyle(fontWeight: FontWeight.w600)),
        ),
      ],
    ),
  );
}
