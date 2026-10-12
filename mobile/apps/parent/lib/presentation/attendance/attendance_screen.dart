import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:school_core/school_core.dart';

import '../../data/parent_repository.dart';
import '../../models/models.dart';
import '../common.dart';

/// Présences of the selected child: summary of the year (computed by the
/// server), convocations, gate scans (when — never who scanned) and the
/// daily history (present, late, absent, excused).
class AttendanceScreen extends StatelessWidget {
  const AttendanceScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(tr('Présences')), actions: const [ChildSwitcher()]),
      body: ChildBody(
        builder: (context, child) => _ChildAttendance(key: ValueKey(child.id), child: child),
      ),
    );
  }
}

class _Data {
  _Data(this.report, this.scans, this.convocations);

  final AttendanceReport report;
  final List<Scan> scans;
  final List<Convocation> convocations;
}

const _scanResultsFr = {'ACCEPTED': 'Entrée enregistrée', 'ALREADY_PRESENT': 'Déjà présent(e)'};

/// Labels in the CURRENT language (French source: [_scanResultsFr]).
Map<String, String> get scanResults => trMap(_scanResultsFr);

Tone dayTone(String status) => switch (status) {
  'PRESENT' => Tone.success,
  'LATE' => Tone.warning,
  'ABSENT' => Tone.danger,
  'EXCUSED' => Tone.info,
  _ => Tone.neutral,
};

class _ChildAttendance extends StatefulWidget {
  const _ChildAttendance({super.key, required this.child});

  final Child child;

  @override
  State<_ChildAttendance> createState() => _ChildAttendanceState();
}

class _ChildAttendanceState extends State<_ChildAttendance> {
  Future<_Data>? _future;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<_Data> _fetch() async {
    final repo = context.read<ParentRepository>();
    final report = await repo.attendance(widget.child.id);
    final scans = await repo.scans(widget.child.id);
    final convocations = (await repo.convocations()).where((c) => c.student == widget.child.id).toList();
    return _Data(report, scans, convocations);
  }

  void _load() => setState(() {
    _future = _fetch()..ignore();
  });

  @override
  Widget build(BuildContext context) {
    return AsyncBody<_Data>(
      future: _future,
      onRetry: _load,
      builder: (context, data) => RefreshIndicator(
        onRefresh: () async {
          _load();
          await _future?.catchError((_) => _Data(AttendanceReport(days: const []), const [], const []));
        },
        child: ListView(
          padding: const EdgeInsets.fromLTRB(16, 8, 16, 24),
          children: [
            Text(widget.child.name, style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w700)),
            Text(widget.child.schooling, style: TextStyle(color: Tokens.textSecondary)),
            SectionTitle(tr('Bilan de l\'année')),
            Card(
              child: Padding(
                padding: const EdgeInsets.all(14),
                child: Column(
                  children: [
                    InfoRow(tr('Absences non justifiées'), '${data.report.unexcused} h', strong: true),
                    InfoRow(tr('Absences justifiées'), '${data.report.excused} h'),
                    InfoRow(tr('Retards'), '${data.report.lateCount}'),
                    if (data.report.alert != null && data.report.alert != 'NONE')
                      Padding(
                        padding: const EdgeInsets.only(top: 8),
                        child: StatusChip(
                          data.report.alertLabel,
                          tone: data.report.alert == 'YELLOW' ? Tone.warning : Tone.danger,
                        ),
                      ),
                  ],
                ),
              ),
            ),
            if (data.convocations.isNotEmpty) ...[
              SectionTitle(tr('Convocations')),
              for (final c in data.convocations)
                Card(
                  child: ListTile(
                    leading: Icon(Icons.event_note, color: Tokens.warning),
                    title: Text(c.start == null ? tr('Convocation') : capitalize(dayLong.format(c.start!))),
                    subtitle: Text(
                      '${c.start == null ? '' : hm.format(c.start!)}${c.end == null ? '' : ' – ${hm.format(c.end!)}'}'
                      ' · ${c.reason}',
                    ),
                    trailing: StatusChip(c.statusLabel, tone: c.status == 'SCHEDULED' ? Tone.warning : Tone.neutral),
                  ),
                ),
            ],
            if (data.scans.isNotEmpty) ...[
              SectionTitle(tr('Passages au portail')),
              Card(
                child: Column(
                  children: [
                    for (final s in data.scans.take(5))
                      ListTile(
                        dense: true,
                        leading: Icon(Icons.qr_code_2, color: Tokens.textSecondary),
                        title: Text(s.at == null ? '' : dateTime.format(s.at!)),
                        subtitle: Text(scanResults[s.result] ?? s.result),
                      ),
                  ],
                ),
              ),
            ],
            SectionTitle(tr('Historique')),
            if (data.report.days.isEmpty)
              Padding(
                padding: EdgeInsets.all(8),
                child: Text(tr('Aucun relevé pour cette année.'), style: TextStyle(color: Tokens.textSecondary)),
              ),
            for (final day in data.report.days)
              Card(
                child: ListTile(
                  title: Text(day.date == null ? '' : capitalize(dayLong.format(day.date!))),
                  subtitle: Text(_detail(day)),
                  trailing: StatusChip(day.statusLabel, tone: dayTone(day.status)),
                ),
              ),
          ],
        ),
      ),
    );
  }

  String _detail(AttendanceDay day) {
    final parts = <String>[
      if (day.arrival != null) tr('Arrivée {0}', [day.arrival!.substring(0, day.arrival!.length.clamp(0, 5))]),
      if (day.lateMinutes > 0) tr('{0} min de retard', [day.lateMinutes]),
      if (day.status == 'ABSENT' || day.status == 'EXCUSED') '${day.absenceHours} h',
      if ((day.note ?? '').isNotEmpty) day.note!,
    ];
    return parts.isEmpty ? '—' : parts.join(' · ');
  }
}
