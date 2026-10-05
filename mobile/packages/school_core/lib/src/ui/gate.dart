/// School gate, shared by the roles allowed to scan (guardian, staff): the
/// EXISTING QR protocol only — no new one.
///
///   POST /qr/scans/ {token}          the server decides: result, the pupil's
///                                    arrival, and the solvency (UP_TO_DATE /
///                                    OVERDUE, never an amount) only for the
///                                    roles allowed to see it (ADR 0014)
///   GET  /guardians/scans/?date=     MY scans only (filtered by the server on
///                                    the caller: never another person's)
///
/// The token is typed or sent by a keyboard-wedge QR reader (camera
/// scanning would need a native plugin: not in this phase).
library;

import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:provider/provider.dart';

import '../api/api_client.dart';
import '../api/api_error.dart';
import '../data/communication.dart';
import '../theme/app_theme.dart';
import '../widgets/widgets.dart';
import 'live_state.dart';

final _day = DateFormat('yyyy-MM-dd');

const scanResults = {
  'ACCEPTED': 'Arrivée enregistrée',
  'ALREADY_PRESENT': 'Déjà présent(e)',
  'UNKNOWN_TOKEN': 'QR inconnu',
  'REVOKED_TOKEN': 'QR révoqué',
  'EXPIRED_TOKEN': 'QR d\'une autre année scolaire',
  'STUDENT_NOT_ENROLLED': 'Élève non inscrit ou inactif',
};
const arrivalStatuses = {'PRESENT': 'À l\'heure', 'LATE': 'En retard', 'ABSENT': 'Absent(e)', 'PENDING': 'En attente'};
const solvencyLabels = {'UP_TO_DATE': 'Scolarité à jour', 'OVERDUE': 'Échéance dépassée'};

bool acceptedScan(String result) => result == 'ACCEPTED' || result == 'ALREADY_PRESENT';

/// What the server answers to a scan (only what this role may see).
class ScanOutcome {
  ScanOutcome({
    required this.result,
    this.at,
    this.studentName,
    this.className,
    this.arrival,
    this.lateMinutes = 0,
    this.solvency,
  });

  factory ScanOutcome.fromJson(Map<String, dynamic> json) {
    final student = (json['student'] as Map?)?.cast<String, dynamic>();
    final attendance = (json['attendance'] as Map?)?.cast<String, dynamic>();
    return ScanOutcome(
      result: (json['result'] as String?) ?? '',
      at: schoolTime(json['scanned_at']),
      studentName: student?['name'] as String?,
      className: student?['class'] as String?,
      arrival: attendance?['status'] as String?,
      lateMinutes: (attendance?['late_minutes'] as int?) ?? 0,
      solvency: json['solvency'] as String?,
    );
  }

  final String result;
  final DateTime? at;
  final String? studentName;
  final String? className;
  final String? arrival;
  final int lateMinutes;

  /// null when this role may not see it.
  final String? solvency;

  bool get accepted => acceptedScan(result);
  String get resultLabel => scanResults[result] ?? result;
}

class ScanRecord {
  ScanRecord({required this.id, required this.result, this.at, this.studentName});

  factory ScanRecord.fromJson(Map<String, dynamic> json) => ScanRecord(
    id: '${json['id']}',
    result: (json['result'] as String?) ?? '',
    at: schoolTime(json['scanned_at']),
    studentName: json['student_name'] as String?,
  );

  final String id;
  final String result;
  final DateTime? at;
  final String? studentName;

  String get resultLabel => scanResults[result] ?? result;
}

class GateRepository {
  GateRepository(this.api);

  final ApiClient api;

  /// Ticks after each scan: the history screens reload themselves.
  final scans = ValueNotifier<int>(0);

  Future<ScanOutcome> scan(String token) async {
    try {
      return ScanOutcome.fromJson(
        (await api.post('qr/scans/', body: {'token': token.trim()}) as Map).cast<String, dynamic>(),
      );
    } finally {
      scans.value++;
    }
  }

  Future<List<ScanRecord>> myScans(DateTime day) async =>
      (await api.listAll('guardians/scans/', params: {'date': _day.format(day)})).map(ScanRecord.fromJson).toList();
}

/// Scan at the gate: token in, the server's answer out.
class ScanScreen extends StatefulWidget {
  const ScanScreen({super.key});

  @override
  State<ScanScreen> createState() => _ScanScreenState();
}

class _ScanScreenState extends State<ScanScreen> {
  final _token = TextEditingController();
  final _focus = FocusNode();
  bool _busy = false;
  ScanOutcome? _last;
  String? _error;

  @override
  void dispose() {
    _token.dispose();
    _focus.dispose();
    super.dispose();
  }

  Future<void> _scan() async {
    final token = _token.text.trim();
    if (token.isEmpty || _busy) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      _last = await context.read<GateRepository>().scan(token);
    } on ApiException catch (error) {
      _last = null;
      _error = error.userMessage;
    } finally {
      _token.clear();
      if (mounted) {
        setState(() => _busy = false);
        _focus.requestFocus(); // ready for the next pupil
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final last = _last;
    return Scaffold(
      appBar: AppBar(title: const Text('Portail'), actions: const [LiveIndicator()]),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          const Text(
            'Présentez la carte de l\'élève au lecteur, ou saisissez le code du QR. Le serveur enregistre '
            'l\'arrivée et décide de ce qui vous est affiché.',
            style: TextStyle(color: Tokens.textSecondary),
          ),
          const SizedBox(height: 14),
          TextField(
            key: const Key('scan.token'),
            controller: _token,
            focusNode: _focus,
            autofocus: true,
            autocorrect: false,
            enableSuggestions: false,
            textInputAction: TextInputAction.done,
            onSubmitted: (_) => _scan(),
            onChanged: (_) => setState(() {}),
            decoration: const InputDecoration(labelText: 'Code du QR', prefixIcon: Icon(Icons.qr_code_scanner)),
          ),
          const SizedBox(height: 12),
          FilledButton.icon(
            key: const Key('scan.submit'),
            onPressed: _token.text.trim().isEmpty || _busy ? null : _scan,
            icon: const Icon(Icons.how_to_reg_outlined),
            label: const Text('Enregistrer le passage'),
          ),
          const SizedBox(height: 18),
          if (_error != null) MessageBanner(_error!),
          if (last != null) ScanOutcomeCard(outcome: last),
        ],
      ),
    );
  }
}

class ScanOutcomeCard extends StatelessWidget {
  const ScanOutcomeCard({super.key, required this.outcome});

  final ScanOutcome outcome;

  @override
  Widget build(BuildContext context) {
    final o = outcome;
    return Card(
      color: o.accepted ? Tokens.successBg : Tokens.errorBg,
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(
                  o.accepted ? Icons.check_circle : Icons.block,
                  color: o.accepted ? Tokens.success : Tokens.error,
                  size: 30,
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: Text(o.resultLabel, style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w700)),
                ),
              ],
            ),
            if (o.studentName != null) ...[
              const SizedBox(height: 10),
              Text(o.studentName!, style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w600)),
              if (o.className != null) Text(o.className!, style: const TextStyle(color: Tokens.textSecondary)),
            ],
            const SizedBox(height: 8),
            Wrap(
              spacing: 6,
              runSpacing: 4,
              children: [
                if (o.arrival != null)
                  StatusChip(
                    o.lateMinutes > 0
                        ? '${arrivalStatuses[o.arrival] ?? o.arrival} (${o.lateMinutes} min)'
                        : (arrivalStatuses[o.arrival] ?? o.arrival!),
                    tone: o.arrival == 'LATE' ? Tone.warning : Tone.success,
                  ),
                if (o.solvency != null)
                  StatusChip(
                    solvencyLabels[o.solvency] ?? o.solvency!,
                    tone: o.solvency == 'OVERDUE' ? Tone.warning : Tone.info,
                  ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

/// MY scans of a day (the server never returns another person's).
class MyScansScreen extends StatefulWidget {
  const MyScansScreen({super.key});

  @override
  State<MyScansScreen> createState() => _MyScansScreenState();
}

class _MyScansScreenState extends State<MyScansScreen> {
  DateTime _day = DateTime.now();
  Future<List<ScanRecord>>? _future;
  late final ValueNotifier<int> _scans;

  @override
  void initState() {
    super.initState();
    _scans = context.read<GateRepository>().scans..addListener(_load);
    _load();
  }

  @override
  void dispose() {
    _scans.removeListener(_load);
    super.dispose();
  }

  void _load() {
    setState(() {
      _future = context.read<GateRepository>().myScans(_day)..ignore();
    });
  }

  void _shift(int days) {
    _day = _day.add(Duration(days: days));
    _load();
  }

  @override
  Widget build(BuildContext context) {
    final today = DateTime.now();
    final isToday = _day.year == today.year && _day.month == today.month && _day.day == today.day;
    return Scaffold(
      appBar: AppBar(
        title: const Text('Mes passages enregistrés'),
        actions: [IconButton(tooltip: 'Actualiser', onPressed: _load, icon: const Icon(Icons.refresh))],
      ),
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(8, 8, 8, 0),
            child: Row(
              children: [
                IconButton(
                  key: const Key('scans.previous'),
                  tooltip: 'Jour précédent',
                  onPressed: () => _shift(-1),
                  icon: const Icon(Icons.chevron_left),
                ),
                Expanded(
                  child: Text(
                    capitalize(dayLong.format(_day)),
                    textAlign: TextAlign.center,
                    style: const TextStyle(fontWeight: FontWeight.w700),
                  ),
                ),
                IconButton(
                  tooltip: 'Jour suivant',
                  onPressed: isToday ? null : () => _shift(1),
                  icon: const Icon(Icons.chevron_right),
                ),
              ],
            ),
          ),
          Expanded(
            child: AsyncBody<List<ScanRecord>>(
              future: _future,
              onRetry: _load,
              isEmpty: (rows) => rows.isEmpty,
              emptyText: 'Aucun passage enregistré par vous ce jour-là.',
              builder: (context, rows) => ListView(
                padding: const EdgeInsets.fromLTRB(12, 4, 12, 24),
                children: [
                  Padding(
                    padding: const EdgeInsets.all(6),
                    child: Text(
                      '${rows.length} passage(s), ${rows.where((r) => acceptedScan(r.result)).length} accepté(s)',
                      style: const TextStyle(color: Tokens.textSecondary),
                    ),
                  ),
                  for (final r in rows)
                    Card(
                      child: ListTile(
                        leading: Icon(
                          acceptedScan(r.result) ? Icons.check_circle_outline : Icons.block,
                          color: acceptedScan(r.result) ? Tokens.success : Tokens.error,
                        ),
                        title: Text(r.studentName ?? 'QR non reconnu'),
                        subtitle: Text('${r.at == null ? '' : hm.format(r.at!)} · ${r.resultLabel}'),
                      ),
                    ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}
