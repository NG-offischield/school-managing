import 'package:flutter/material.dart';
import 'package:school_core/school_core.dart';

import '../models/models.dart';

String hours(TeachingSession s) =>
    s.start == null || s.end == null ? '' : '${hm.format(s.start!)} – ${hm.format(s.end!)}';

Tone sessionTone(TeachingSession s) => switch (s.status) {
  'CANCELLED' => Tone.danger,
  'COMPLETED' => Tone.success,
  _ => s.substituted || s.moved ? Tone.warning : Tone.info,
};

/// "Remplace X" when I teach instead of the planned teacher; "Remplacé par
/// Y" when I was planned and someone else teaches (names from the server).
String? substitutionNote(TeachingSession s, String myName) {
  if (!s.substituted) return null;
  if (s.teacher.label == myName) return 'Vous remplacez ${s.plannedTeacher.label}';
  return 'Remplacé par ${s.teacher.label}';
}

class SessionTile extends StatelessWidget {
  const SessionTile({super.key, required this.session, required this.myName, this.onTap, this.showDay = false});

  final TeachingSession session;
  final String myName;
  final VoidCallback? onTap;
  final bool showDay;

  @override
  Widget build(BuildContext context) {
    final note = substitutionNote(session, myName);
    final room = session.room == null ? 'Salle non attribuée' : 'Salle ${session.room!.label}';
    return Card(
      child: InkWell(
        borderRadius: BorderRadius.circular(10),
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.all(14),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              SizedBox(
                width: 64,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    if (showDay && session.start != null)
                      Text(
                        capitalize(dayShort.format(session.start!)),
                        style: TextStyle(fontSize: 12, color: Tokens.textSecondary),
                      ),
                    Text(
                      session.start == null ? '' : hm.format(session.start!),
                      style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w700),
                    ),
                    Text(
                      session.end == null ? '' : hm.format(session.end!),
                      style: TextStyle(color: Tokens.textSecondary),
                    ),
                  ],
                ),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      session.title,
                      style: TextStyle(
                        fontSize: 16,
                        fontWeight: FontWeight.w700,
                        decoration: session.cancelled ? TextDecoration.lineThrough : null,
                      ),
                    ),
                    const SizedBox(height: 2),
                    Text('${session.subject.extra} · $room', style: TextStyle(color: Tokens.textSecondary)),
                    if (note != null) ...[
                      const SizedBox(height: 4),
                      Text(
                        note,
                        style: TextStyle(color: Tokens.warning, fontWeight: FontWeight.w600),
                      ),
                    ],
                    const SizedBox(height: 8),
                    Wrap(
                      spacing: 6,
                      runSpacing: 4,
                      children: [
                        StatusChip(session.statusLabel, tone: sessionTone(session)),
                        if (session.moved && !session.cancelled) const StatusChip('Déplacée', tone: Tone.warning),
                      ],
                    ),
                  ],
                ),
              ),
              if (onTap != null) Icon(Icons.chevron_right, color: Tokens.textSecondary),
            ],
          ),
        ),
      ),
    );
  }
}

class SectionTitle extends StatelessWidget {
  const SectionTitle(this.text, {super.key, this.trailing});

  final String text;
  final Widget? trailing;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(2, 18, 2, 8),
      child: Row(
        children: [
          Expanded(
            child: Text(
              text,
              style: TextStyle(fontSize: 17, fontWeight: FontWeight.w700, color: Tokens.text),
            ),
          ),
          ?trailing,
        ],
      ),
    );
  }
}
