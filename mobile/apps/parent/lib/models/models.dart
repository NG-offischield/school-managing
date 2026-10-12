/// Data of the parent app, as returned by the API (read models only: every
/// rule — which child, which right, which document — stays on the server).
library;

import 'package:school_core/school_core.dart';

DateTime? _date(Object? iso) => iso == null ? null : DateTime.tryParse('$iso');

const _relationshipsFr = {
  'MOTHER': 'Mère',
  'FATHER': 'Père',
  'LEGAL_GUARDIAN': 'Tuteur légal',
  'TUTOR': 'Tuteur',
  'OTHER': 'Autre',
};

/// Labels in the CURRENT language (French source: [_relationshipsFr]).
Map<String, String> get relationships => trMap(_relationshipsFr);

const _documentTypesFr = {
  'CNI': 'Carte nationale d\'identité',
  'PASSPORT': 'Passeport',
  'RESIDENCE_PERMIT': 'Titre de séjour',
  'OTHER': 'Autre pièce officielle',
};

/// Labels in the CURRENT language (French source: [_documentTypesFr]).
Map<String, String> get documentTypes => trMap(_documentTypesFr);

const _enrollmentStatusesFr = {'ACTIVE': 'Scolarisé(e)', 'COMPLETED': 'Année terminée', 'WITHDRAWN': 'Retiré(e)'};

/// Labels in the CURRENT language (French source: [_enrollmentStatusesFr]).
Map<String, String> get enrollmentStatuses => trMap(_enrollmentStatusesFr);

/// A child the server lets this parent see: a VERIFIED, active link, with
/// the rights the school granted on that link.
class Child {
  Child({
    required this.linkId,
    required this.id,
    required this.firstName,
    required this.lastName,
    required this.studentNumber,
    required this.relationship,
    required this.canPay,
    required this.canViewFinance,
    required this.canReceiveNotifications,
    required this.canSubmitComplaints,
    this.className,
    this.yearName,
    this.enrollmentStatus,
  });

  factory Child.fromJson(Map<String, dynamic> json) {
    final student = ((json['student'] as Map?) ?? const {}).cast<String, dynamic>();
    final enrollment = (json['enrollment'] as Map?)?.cast<String, dynamic>();
    return Child(
      linkId: '${json['id']}',
      id: '${student['id']}',
      firstName: (student['first_name'] as String?) ?? '',
      lastName: (student['last_name'] as String?) ?? '',
      studentNumber: (student['student_number'] as String?) ?? '',
      relationship: (json['relationship_type'] as String?) ?? '',
      canPay: json['can_pay'] == true,
      canViewFinance: json['can_view_financial_data'] == true,
      canReceiveNotifications: json['can_receive_notifications'] == true,
      canSubmitComplaints: json['can_submit_complaints'] == true,
      className: enrollment?['class_name'] as String?,
      yearName: enrollment?['academic_year_name'] as String?,
      enrollmentStatus: enrollment?['status'] as String?,
    );
  }

  final String linkId;
  final String id;
  final String firstName;
  final String lastName;
  final String studentNumber;
  final String relationship;
  final bool canPay;
  final bool canViewFinance;
  final bool canReceiveNotifications;
  final bool canSubmitComplaints;
  final String? className;
  final String? yearName;
  final String? enrollmentStatus;

  String get name => '$firstName $lastName'.trim();

  String get schooling {
    if (className == null) return tr('Pas d\'inscription cette année');
    final status = enrollmentStatuses[enrollmentStatus] ?? enrollmentStatus ?? '';
    return '$className · ${yearName ?? ''}${status.isEmpty || enrollmentStatus == 'ACTIVE' ? '' : ' · $status'}';
  }
}

const _registrationStatusesFr = {'PENDING': 'En attente de validation', 'APPROVED': 'Validée', 'REJECTED': 'Refusée'};

/// Labels in the CURRENT language (French source: [_registrationStatusesFr]).
Map<String, String> get registrationStatuses => trMap(_registrationStatusesFr);

class Registration {
  Registration({required this.status, required this.schoolName, this.submittedAt, this.rejectionReason});

  factory Registration.fromJson(Map<String, dynamic> json) => Registration(
    status: (json['status'] as String?) ?? '',
    schoolName: (json['school_name'] as String?) ?? '',
    submittedAt: schoolTime(json['submitted_at']),
    rejectionReason: json['rejection_reason'] as String?,
  );

  final String status;
  final String schoolName;
  final DateTime? submittedAt;
  final String? rejectionReason;

  String get statusLabel => registrationStatuses[status] ?? status;
}

const _linkStatusesFr = {'PENDING': 'En cours', 'APPROVED': 'Validée', 'REJECTED': 'Refusée', 'CANCELLED': 'Annulée'};

/// Labels in the CURRENT language (French source: [_linkStatusesFr]).
Map<String, String> get linkStatuses => trMap(_linkStatusesFr);
const _identityStatusesFr = {'PENDING': 'À vérifier à l\'école', 'VERIFIED': 'Vérifiée', 'REJECTED': 'Refusée'};

/// Labels in the CURRENT language (French source: [_identityStatusesFr]).
Map<String, String> get identityStatuses => trMap(_identityStatusesFr);
const _studentApprovalsFr = {
  'PENDING': 'À confirmer par l\'élève',
  'APPROVED': 'Confirmée par l\'élève',
  'REJECTED': 'Refusée par l\'élève',
  'NOT_REQUIRED': 'Non requise',
};

/// Labels in the CURRENT language (French source: [_studentApprovalsFr]).
Map<String, String> get studentApprovals => trMap(_studentApprovalsFr);

/// « This is my child » request, as the parent may see it (never the
/// document number: the server keeps an HMAC only).
class LinkRequest {
  LinkRequest({
    required this.id,
    required this.studentName,
    required this.relationship,
    required this.status,
    required this.identityStatus,
    required this.identityMethod,
    required this.studentApproval,
    required this.sponsored,
    this.createdAt,
    this.decisionReason,
  });

  factory LinkRequest.fromJson(Map<String, dynamic> json) => LinkRequest(
    id: '${json['id']}',
    studentName: ((json['student'] as Map?)?['name'] as String?) ?? '',
    relationship: (json['relationship_type'] as String?) ?? '',
    status: (json['status'] as String?) ?? '',
    identityStatus: (json['identity_status'] as String?) ?? '',
    identityMethod: (json['identity_method'] as String?) ?? '',
    studentApproval: (json['student_approval_status'] as String?) ?? '',
    sponsored: json['sponsored'] == true,
    createdAt: schoolTime(json['created_at']),
    decisionReason: json['decision_reason'] as String?,
  );

  final String id;
  final String studentName;
  final String relationship;
  final String status;
  final String identityStatus;
  final String identityMethod;
  final String studentApproval;
  final bool sponsored;
  final DateTime? createdAt;
  final String? decisionReason;

  bool get pending => status == 'PENDING';
  String get statusLabel => linkStatuses[status] ?? status;
  String get identityLabel =>
      sponsored ? tr('Vérifiée par parrainage') : (identityStatuses[identityStatus] ?? identityStatus);
  String get approvalLabel => studentApprovals[studentApproval] ?? studentApproval;
}

const _dailyStatusesFr = {
  'PENDING': 'En attente',
  'PRESENT': 'Présent(e)',
  'LATE': 'En retard',
  'ABSENT': 'Absent(e)',
  'EXCUSED': 'Absence justifiée',
};

/// Labels in the CURRENT language (French source: [_dailyStatusesFr]).
Map<String, String> get dailyStatuses => trMap(_dailyStatusesFr);
const _alertLevelsFr = {
  'NONE': 'Aucune alerte',
  'YELLOW': 'Alerte jaune',
  'ORANGE': 'Alerte orange',
  'RED': 'Alerte rouge',
};

/// Labels in the CURRENT language (French source: [_alertLevelsFr]).
Map<String, String> get alertLevels => trMap(_alertLevelsFr);

class AttendanceDay {
  AttendanceDay({
    required this.date,
    required this.status,
    this.arrival,
    this.lateMinutes = 0,
    this.absenceHours = '0',
    this.note,
  });

  factory AttendanceDay.fromJson(Map<String, dynamic> json) => AttendanceDay(
    date: _date(json['date']),
    status: (json['status'] as String?) ?? '',
    arrival: (json['arrival_time'] as String?),
    lateMinutes: (json['late_minutes'] as int?) ?? 0,
    absenceHours: '${json['absence_hours'] ?? '0'}',
    note: json['note'] as String?,
  );

  final DateTime? date;
  final String status;
  final String? arrival;
  final int lateMinutes;
  final String absenceHours;
  final String? note;

  String get statusLabel => dailyStatuses[status] ?? status;
}

class AttendanceReport {
  AttendanceReport({required this.days, this.unexcused = '0', this.excused = '0', this.lateCount = 0, this.alert});

  factory AttendanceReport.fromJson(Map<String, dynamic> json) {
    final summary = (json['summary'] as Map?)?.cast<String, dynamic>() ?? const {};
    return AttendanceReport(
      days: ((json['records'] as List?) ?? const [])
          .map((r) => AttendanceDay.fromJson((r as Map).cast<String, dynamic>()))
          .toList(),
      unexcused: '${summary['unexcused_absence_hours'] ?? '0'}',
      excused: '${summary['excused_absence_hours'] ?? '0'}',
      lateCount: (summary['late_count'] as int?) ?? 0,
      alert: summary['alert_level'] as String?,
    );
  }

  final List<AttendanceDay> days;
  final String unexcused;
  final String excused;
  final int lateCount;
  final String? alert;

  String get alertLabel => alertLevels[alert] ?? (alert ?? '');
}

/// The child was scanned at the gate — when, never who scanned.
class Scan {
  Scan({required this.at, required this.result});

  factory Scan.fromJson(Map<String, dynamic> json) =>
      Scan(at: schoolTime(json['scanned_at']), result: (json['result'] as String?) ?? '');

  final DateTime? at;
  final String result;
}

const _convocationStatusesFr = {
  'SCHEDULED': 'Programmée',
  'HELD': 'Tenue',
  'MISSED': 'Parent absent',
  'CANCELLED': 'Annulée',
};

/// Labels in the CURRENT language (French source: [_convocationStatusesFr]).
Map<String, String> get convocationStatuses => trMap(_convocationStatusesFr);

class Convocation {
  Convocation({required this.student, required this.start, required this.reason, required this.status, this.end});

  factory Convocation.fromJson(Map<String, dynamic> json) => Convocation(
    student: '${json['student']}',
    start: schoolTime(json['scheduled_start']),
    end: schoolTime(json['scheduled_end']),
    reason: (json['reason'] as String?) ?? '',
    status: (json['status'] as String?) ?? '',
  );

  final String student;
  final DateTime? start;
  final DateTime? end;
  final String reason;
  final String status;

  String get statusLabel => convocationStatuses[status] ?? status;
}

const _sessionStatusesFr = {'SCHEDULED': 'Prévue', 'COMPLETED': 'Réalisée', 'CANCELLED': 'Annulée'};

/// Labels in the CURRENT language (French source: [_sessionStatusesFr]).
Map<String, String> get sessionStatuses => trMap(_sessionStatusesFr);

/// A dated session of the child's class (families see what, when, where,
/// who teaches — no internal data).
class ClassSession {
  ClassSession({
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
    this.originalStart,
  });

  factory ClassSession.fromJson(Map<String, dynamic> json) => ClassSession(
    id: '${json['id']}',
    subject: Ref.of(json['subject'], 'code', 'name'),
    schoolClass: Ref.of(json['school_class'], 'name'),
    teacher: Ref.of(json['teacher'], 'name'),
    room: json['room'] == null ? null : Ref.of(json['room'], 'code', 'name'),
    start: schoolTime(json['scheduled_start']),
    end: schoolTime(json['scheduled_end']),
    originalStart: schoolTime(json['original_start']),
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
  final DateTime? originalStart;
  final String status;
  final bool substituted;
  final bool moved;

  bool get cancelled => status == 'CANCELLED';
  String get statusLabel => sessionStatuses[status] ?? status;
  String get subjectName => subject.extra.isNotEmpty ? subject.extra : subject.label;
}

const _invoiceStatusesFr = {
  'ISSUED': 'À payer',
  'PARTIALLY_PAID': 'Partiellement payée',
  'PAID': 'Payée',
  'CANCELLED': 'Annulée',
};

/// Labels in the CURRENT language (French source: [_invoiceStatusesFr]).
Map<String, String> get invoiceStatuses => trMap(_invoiceStatusesFr);
const _solvenciesFr = {'UP_TO_DATE': 'À jour', 'OVERDUE': 'Échéance dépassée'};

/// Labels in the CURRENT language (French source: [_solvenciesFr]).
Map<String, String> get solvencies => trMap(_solvenciesFr);

class InvoiceLine {
  InvoiceLine({required this.label, required this.total});

  factory InvoiceLine.fromJson(Map<String, dynamic> json) => InvoiceLine(
    label: (json['description'] as String?)?.isNotEmpty == true
        ? json['description'] as String
        : '${json['fee_type_code'] ?? ''}',
    total: '${json['total'] ?? '0'}',
  );

  final String label;
  final String total;
}

class Invoice {
  Invoice({
    required this.id,
    required this.number,
    required this.status,
    required this.total,
    required this.paid,
    required this.balance,
    required this.currency,
    required this.lines,
    this.issueDate,
    this.dueDate,
  });

  factory Invoice.fromJson(Map<String, dynamic> json) => Invoice(
    id: '${json['id']}',
    number: (json['invoice_number'] as String?) ?? '',
    status: (json['status'] as String?) ?? '',
    total: '${json['total_amount'] ?? '0'}',
    paid: '${json['amount_paid'] ?? '0'}',
    balance: '${json['balance_due'] ?? '0'}',
    currency: (json['currency'] as String?) ?? 'XAF',
    lines: ((json['lines'] as List?) ?? const [])
        .map((l) => InvoiceLine.fromJson((l as Map).cast<String, dynamic>()))
        .toList(),
    issueDate: _date(json['issue_date']),
    dueDate: _date(json['due_date']),
  );

  final String id;
  final String number;
  final String status;
  final String total;
  final String paid;
  final String balance;
  final String currency;
  final List<InvoiceLine> lines;
  final DateTime? issueDate;
  final DateTime? dueDate;

  String get statusLabel => invoiceStatuses[status] ?? status;

  /// The server's status says it is still to be paid (the amount is its balance_due).
  bool get payable => status == 'ISSUED' || status == 'PARTIALLY_PAID';

  /// Motif: the lines of the invoice, as issued by the school.
  String get reason => lines.map((l) => l.label).where((l) => l.isNotEmpty).join(', ');
}

/// The payer's own mobile wallet (opened by the school, ADR 0013 §12.4).
class Wallet {
  Wallet({
    required this.id,
    required this.provider,
    required this.identifier,
    required this.balance,
    required this.currency,
    required this.status,
  });

  factory Wallet.fromJson(Map<String, dynamic> json) => Wallet(
    id: '${json['id']}',
    provider: (json['provider_code'] as String?) ?? '',
    identifier: (json['wallet_identifier'] as String?) ?? '',
    balance: '${json['balance'] ?? '0'}',
    currency: (json['currency'] as String?) ?? 'XAF',
    status: (json['status'] as String?) ?? '',
  );

  final String id;
  final String provider;
  final String identifier;
  final String balance;
  final String currency;
  final String status;

  bool get active => status == 'ACTIVE';

  /// "FAKE ••0633": never the whole number on screen.
  String get label {
    final tail = identifier.length > 4 ? identifier.substring(identifier.length - 4) : identifier;
    return '$provider ••$tail';
  }
}

/// What the child's account owes, computed by the server (amounts are
/// strings: never recomputed here). `canPay` is the SERVER's answer.
class Obligations {
  Obligations({
    required this.currency,
    required this.balanceDue,
    required this.solvency,
    required this.canPay,
    required this.openInvoices,
  });

  factory Obligations.fromJson(Map<String, dynamic> json) => Obligations(
    currency: (json['currency'] as String?) ?? 'XAF',
    balanceDue: '${json['balance_due'] ?? '0'}',
    solvency: (json['solvency'] as String?) ?? '',
    canPay: json['can_pay'] == true,
    openInvoices: ((json['open_invoices'] as List?) ?? const [])
        .map((i) => Invoice.fromJson((i as Map).cast<String, dynamic>()))
        .toList(),
  );

  final String currency;
  final String balanceDue;
  final String solvency;
  final bool canPay;
  final List<Invoice> openInvoices;

  String get solvencyLabel => solvencies[solvency] ?? solvency;
}

const _paymentStatusesFr = {
  'PENDING': 'En attente',
  'SUCCEEDED': 'Réussi',
  'DECLINED': 'Refusé',
  'INSUFFICIENT_FUNDS': 'Fonds insuffisants',
  'TIMEOUT': 'Délai dépassé',
  'PROVIDER_ERROR': 'Erreur du fournisseur',
  'CANCELLED': 'Annulé',
  'PARTIALLY_REFUNDED': 'Partiellement remboursé',
  'REFUNDED': 'Remboursé',
};

/// Labels in the CURRENT language (French source: [_paymentStatusesFr]).
Map<String, String> get paymentStatuses => trMap(_paymentStatusesFr);

/// What the payer is told about a payment the server answered. A failure is
/// a RESULT recorded by the server, never computed here; a failed payment
/// moves no money (ADR 0013 §4).
const _paymentOutcomesFr = {
  'SUCCEEDED': 'Paiement réussi',
  'PENDING': 'Paiement en attente de confirmation du fournisseur',
  'DECLINED': 'Paiement refusé par le fournisseur : aucun débit',
  'INSUFFICIENT_FUNDS': 'Solde du portefeuille insuffisant : aucun débit',
  'TIMEOUT': 'Le fournisseur n\x27a pas répondu à temps : aucun débit',
  'PROVIDER_ERROR': 'Erreur du fournisseur : aucun débit',
  'CANCELLED': 'Paiement annulé : aucun débit',
};

/// Labels in the CURRENT language (French source: [_paymentOutcomesFr]).
Map<String, String> get paymentOutcomes => trMap(_paymentOutcomesFr);

class Payment {
  Payment({
    required this.id,
    required this.reference,
    required this.amount,
    required this.currency,
    required this.status,
    this.at,
    this.failureReason,
    this.invoiceNumbers = const [],
    this.replayed = false,
  });

  factory Payment.fromJson(Map<String, dynamic> json) => Payment(
    id: '${json['id']}',
    reference: (json['payment_reference'] as String?) ?? '',
    amount: '${json['amount'] ?? '0'}',
    currency: (json['currency'] as String?) ?? 'XAF',
    status: (json['status'] as String?) ?? '',
    at: schoolTime(json['completed_at'] ?? json['initiated_at']),
    failureReason: (json['failure_reason'] as String?)?.trim().isNotEmpty == true
        ? json['failure_reason'] as String
        : null,
    invoiceNumbers: ((json['allocations'] as List?) ?? const [])
        .map((a) => '${(a as Map)['invoice_number'] ?? ''}')
        .where((n) => n.isNotEmpty)
        .toSet()
        .toList(),
    replayed: json['replayed'] == true,
  );

  final String id;
  final String reference;
  final String amount;
  final String currency;
  final String status;
  final DateTime? at;

  /// The provider's explanation of a failure, as recorded by the server.
  final String? failureReason;
  final List<String> invoiceNumbers;

  /// The server answered with the payment ALREADY created for this
  /// idempotency key (retry after a lost answer): nothing was debited again.
  final bool replayed;

  String get statusLabel => paymentStatuses[status] ?? status;
  String get outcome => paymentOutcomes[status] ?? statusLabel;
  bool get succeeded => status == 'SUCCEEDED';

  /// A receipt exists once the payment went through (the server checks again).
  bool get hasReceipt => status == 'SUCCEEDED' || status == 'PARTIALLY_REFUNDED' || status == 'REFUNDED';
}

class ReportCardLine {
  ReportCardLine({required this.subject, required this.average, required this.coefficient, this.appreciation});

  factory ReportCardLine.fromJson(Map<String, dynamic> json) => ReportCardLine(
    subject: (json['subject_name'] as String?) ?? (json['subject_code'] as String?) ?? '',
    average: json['average'] == null ? null : '${json['average']}',
    coefficient: '${json['coefficient'] ?? ''}',
    appreciation: json['appreciation'] as String?,
  );

  final String subject;
  final String? average;
  final String coefficient;
  final String? appreciation;
}

/// An OFFICIAL (validated) report card: the server never gives a parent a
/// provisional one.
class ReportCard {
  ReportCard({
    required this.id,
    required this.period,
    required this.status,
    required this.lines,
    this.average,
    this.scaleMax,
    this.rank,
    this.classSize,
    this.validatedAt,
  });

  factory ReportCard.fromJson(Map<String, dynamic> json) => ReportCard(
    id: '${json['id']}',
    period: (json['period_name'] as String?) ?? '',
    status: (json['status'] as String?) ?? '',
    average: json['general_average'] == null ? null : '${json['general_average']}',
    scaleMax: json['scale_max_score'] == null ? null : '${json['scale_max_score']}',
    rank: json['rank'] as int?,
    classSize: json['class_size'] as int?,
    validatedAt: schoolTime(json['validated_at']),
    lines: ((json['lines'] as List?) ?? const [])
        .map((l) => ReportCardLine.fromJson((l as Map).cast<String, dynamic>()))
        .toList(),
  );

  final String id;
  final String period;
  final String status;
  final String? average;
  final String? scaleMax;
  final int? rank;
  final int? classSize;
  final DateTime? validatedAt;
  final List<ReportCardLine> lines;
}

class TeacherContact {
  TeacherContact({required this.member, required this.name, required this.subjects});

  factory TeacherContact.fromJson(Map<String, dynamic> json) => TeacherContact(
    member: '${json['member']}',
    name: (json['name'] as String?) ?? '',
    subjects: ((json['subjects'] as List?) ?? const []).map((s) => '$s').toList(),
  );

  final String member;
  final String name;
  final List<String> subjects;
}

/// Answer of the authenticity check of a printed document.
class DocumentCheck {
  DocumentCheck({required this.kind, required this.status, required this.current, this.title});

  factory DocumentCheck.fromJson(Map<String, dynamic> json) => DocumentCheck(
    kind: (json['kind'] as String?) ?? '',
    status: (json['status'] as String?) ?? '',
    current: json['current'] == true,
    title: json['title'] as String?,
  );

  final String kind;
  final String status;
  final bool current;
  final String? title;
}
