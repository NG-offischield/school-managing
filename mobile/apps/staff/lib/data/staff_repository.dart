/// What the staff app reads, through the EXISTING API only; the server
/// limits everything to the caller's school and permissions:
///
///   GET /staff/                       my own staff record (+ functions) — others are not listed
///   GET /sessions/?date_from&date_to  the school's planning (staff may read it)
///   GET /planning/changes/?date_from= recent planning changes
///   GET /school-breaks/               closures
///   GET /payroll/me/  /payroll/me/{id}/   MY approved / paid payrolls only
///   gate (school_core GateRepository): POST /qr/scans/, GET /guardians/scans/ (MY scans)
///   communication (school_core CommunicationRepository)
///
/// No staff attendance API exists yet: the app says so instead of inventing one.
library;

import 'package:intl/intl.dart';
import 'package:school_core/school_core.dart';

final _day = DateFormat('yyyy-MM-dd');

class StaffMe {
  StaffMe({required this.staffNumber, required this.employeeNumber, required this.functions});

  factory StaffMe.fromJson(Map<String, dynamic> json) => StaffMe(
    staffNumber: (json['staff_number'] as String?) ?? '',
    employeeNumber: (json['employee_number'] as String?) ?? '',
    functions: ((json['function_labels'] as List?) ?? const [])
        .map((f) => Ref('${(f as Map)['code']}', '${f['name']}'))
        .toList(),
  );

  final String staffNumber;
  final String employeeNumber;
  final List<Ref> functions; // id = code, label = name
}

const _sessionStatusesFr = {'SCHEDULED': 'Prévue', 'COMPLETED': 'Réalisée', 'CANCELLED': 'Annulée'};

/// Labels in the CURRENT language (French source: [_sessionStatusesFr]).
Map<String, String> get sessionStatuses => trMap(_sessionStatusesFr);

class SchoolSession {
  SchoolSession({
    required this.id,
    required this.subject,
    required this.schoolClass,
    required this.teacher,
    required this.room,
    required this.start,
    required this.end,
    required this.status,
    required this.substituted,
    required this.moved,
  });

  factory SchoolSession.fromJson(Map<String, dynamic> json) => SchoolSession(
    id: '${json['id']}',
    subject: Ref.of(json['subject'], 'code', 'name'),
    schoolClass: Ref.of(json['school_class'], 'name'),
    teacher: Ref.of(json['teacher'], 'name'),
    room: json['room'] == null ? null : Ref.of(json['room'], 'code', 'name'),
    start: schoolTime(json['scheduled_start']),
    end: schoolTime(json['scheduled_end']),
    status: (json['status'] as String?) ?? '',
    substituted: json['is_substituted'] == true,
    moved: json['is_moved'] == true,
  );

  final String id;
  final Ref subject;
  final Ref schoolClass;
  final Ref teacher;
  final Ref? room;
  final DateTime? start;
  final DateTime? end;
  final String status;
  final bool substituted;
  final bool moved;

  bool get cancelled => status == 'CANCELLED';
  String get statusLabel => sessionStatuses[status] ?? status;
  String get subjectName => subject.extra.isNotEmpty ? subject.extra : subject.label;
}

const _changeTypesFr = {
  'SLOT_CREATED': 'Créneau ajouté',
  'SLOT_ENDED': 'Créneau arrêté',
  'SLOT_ARCHIVED': 'Créneau archivé',
  'SESSION_CREATED': 'Séance exceptionnelle',
  'SESSION_CANCELLED': 'Séance annulée',
  'SESSION_MOVED': 'Séance déplacée',
  'SESSION_ROOM_CHANGED': 'Changement de salle',
  'TEACHER_SUBSTITUTED': 'Enseignant remplacé',
  'TEACHER_RESTORED': 'Enseignant rétabli',
  'SESSIONS_SWAPPED': 'Séances échangées',
};

/// Labels in the CURRENT language (French source: [_changeTypesFr]).
Map<String, String> get changeTypes => trMap(_changeTypesFr);

const _lineKindsFr = {
  'SALARY': 'Salaire fixe',
  'ADJUSTMENT': 'Correction',
  'EARNED': 'Séance validée',
  'PROGRAMMED': 'Séance programmée',
};

/// Labels in the CURRENT language (French source: [_lineKindsFr]).
Map<String, String> get lineKinds => trMap(_lineKindsFr);

class PlanningChange {
  PlanningChange({required this.type, this.at, this.reason, this.date});

  factory PlanningChange.fromJson(Map<String, dynamic> json) {
    final next = ((json['new_data'] as Map?) ?? const {}).cast<String, dynamic>();
    return PlanningChange(
      type: (json['change_type'] as String?) ?? '',
      at: schoolTime(json['changed_at']),
      reason: json['reason'] as String?,
      date: next['date'] as String?,
    );
  }

  final String type;
  final DateTime? at;
  final String? reason;
  final String? date;

  String get typeLabel => changeTypes[type] ?? type;
}

const _payrollStatusesFr = {'APPROVED': 'Validée', 'PAID': 'Payée'};

/// Labels in the CURRENT language (French source: [_payrollStatusesFr]).
Map<String, String> get payrollStatuses => trMap(_payrollStatusesFr);

class Payslip {
  Payslip({
    required this.id,
    required this.period,
    required this.status,
    required this.payable,
    required this.currency,
    this.base,
    this.gross,
    this.adjustments,
    this.paidAt,
    this.lines = const [],
  });

  factory Payslip.fromJson(Map<String, dynamic> json) => Payslip(
    id: '${json['id']}',
    period: (json['period_name'] as String?) ?? '',
    status: (json['status'] as String?) ?? '',
    payable: '${json['payable_amount'] ?? '0'}',
    currency: (json['currency'] as String?) ?? 'XAF',
    base: json['base_salary'] as String?,
    gross: json['gross_amount'] as String?,
    adjustments: json['adjustments_amount'] as String?,
    paidAt: schoolTime(json['paid_at']),
    lines: ((json['lines'] as List?) ?? const [])
        .map((l) => (l as Map).cast<String, dynamic>())
        .map((l) => Ref('${l['kind']}', '${l['amount']}'))
        .toList(),
  );

  final String id;
  final String period;
  final String status;
  final String payable;
  final String currency;
  final String? base;
  final String? gross;
  final String? adjustments;
  final DateTime? paidAt;
  final List<Ref> lines; // id = kind, label = amount

  String get statusLabel => payrollStatuses[status] ?? status;
}

class StaffRepository extends CommunicationRepository {
  StaffRepository(super.api) : gate = GateRepository(api);

  final GateRepository gate;

  /// My staff record; null when this account has none (e.g. not set up yet).
  Future<StaffMe?> me() async {
    final rows = await api.listAll('staff/');
    return rows.isEmpty ? null : StaffMe.fromJson(rows.first);
  }

  Future<List<SchoolSession>> sessions(DateTime from, DateTime to) async {
    final rows = await api.listAll('sessions/', params: {'date_from': _day.format(from), 'date_to': _day.format(to)});
    return rows.map(SchoolSession.fromJson).toList()
      ..sort((a, b) => (a.start ?? DateTime(0)).compareTo(b.start ?? DateTime(0)));
  }

  Future<List<PlanningChange>> changes({required DateTime since}) async => (await api.page(
    'planning/changes/',
    pageSize: 20,
    params: {'date_from': _day.format(since)},
  )).rows.map(PlanningChange.fromJson).toList();

  Future<List<SchoolBreakItem>> breaks() => upcomingBreaks(api);

  Future<List<Payslip>> payslips() async => ((await api.get('payroll/me/') as List?) ?? const [])
      .map((p) => Payslip.fromJson((p as Map).cast<String, dynamic>()))
      .toList();

  Future<Payslip> payslip(String id) async =>
      Payslip.fromJson((await api.get('payroll/me/$id/') as Map).cast<String, dynamic>());
}
