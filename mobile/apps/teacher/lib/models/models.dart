/// Data of the teacher app, as returned by the API (read models only:
/// every rule stays on the server).
library;

import 'package:school_core/school_core.dart';

const _sessionStatusesFr = {'SCHEDULED': 'Prévue', 'COMPLETED': 'Réalisée', 'CANCELLED': 'Annulée'};

/// Labels in the CURRENT language (French source: [_sessionStatusesFr]).
Map<String, String> get sessionStatuses => trMap(_sessionStatusesFr);

class TeachingSession {
  TeachingSession({
    required this.id,
    required this.subject,
    required this.schoolClass,
    required this.teacher,
    required this.plannedTeacher,
    required this.room,
    required this.start,
    required this.end,
    required this.status,
    required this.substituted,
    required this.moved,
  });

  factory TeachingSession.fromJson(Map<String, dynamic> json) => TeachingSession(
    id: '${json['id']}',
    subject: Ref.of(json['subject'], 'code', 'name'),
    schoolClass: Ref.of(json['school_class'], 'name'),
    teacher: Ref.of(json['teacher'], 'name'),
    plannedTeacher: Ref.of(json['planned_teacher'], 'name'),
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
  final Ref plannedTeacher;
  final Ref? room;
  final DateTime? start;
  final DateTime? end;
  final String status;
  final bool substituted;
  final bool moved;

  bool get cancelled => status == 'CANCELLED';
  String get statusLabel => sessionStatuses[status] ?? status;
  String get title => '${subject.label} — ${schoolClass.label}';
}

class Course {
  Course({
    required this.id,
    required this.className,
    required this.subjectCode,
    required this.coefficient,
    required this.weeklyHours,
    required this.active,
  });

  factory Course.fromJson(Map<String, dynamic> json) => Course(
    id: '${json['id']}',
    className: (json['class_name'] as String?) ?? '',
    subjectCode: (json['subject_code'] as String?) ?? '',
    coefficient: '${json['coefficient'] ?? ''}',
    weeklyHours: json['weekly_hours'] == null ? '' : '${json['weekly_hours']}',
    active: json['active'] != false,
  );

  final String id;
  final String className;
  final String subjectCode;
  final String coefficient;
  final String weeklyHours;
  final bool active;
}

class ScheduleChangeItem {
  ScheduleChangeItem({required this.type, required this.at, required this.reason});

  factory ScheduleChangeItem.fromJson(Map<String, dynamic> json) => ScheduleChangeItem(
    type: (json['change_type'] as String?) ?? '',
    at: schoolTime(json['changed_at']),
    reason: (json['reason'] as String?) ?? '',
  );

  static Map<String, String> get labels => trMap(_labelsFr);

  static const _labelsFr = {
    'SESSION_CREATED': 'Séance ajoutée',
    'SESSION_CANCELLED': 'Séance annulée',
    'SESSION_MOVED': 'Séance déplacée',
    'SESSION_ROOM_CHANGED': 'Changement de salle',
    'TEACHER_SUBSTITUTED': 'Enseignant remplacé',
    'TEACHER_RESTORED': 'Enseignant prévu rétabli',
    'SESSIONS_SWAPPED': 'Séances échangées',
    'SLOT_CREATED': 'Créneau ajouté',
    'SLOT_ENDED': 'Créneau terminé',
  };

  final String type;
  final DateTime? at;
  final String reason;

  String get label => labels[type] ?? type;
}

/// Live remuneration for a range, as computed by the server (teacher/payroll/).
class PaySummary {
  PaySummary({required this.programmed, required this.earned, required this.paid, required this.sessions});

  factory PaySummary.fromJson(Map<String, dynamic> json) {
    final live = ((json['live'] as Map?) ?? const {}).cast<String, dynamic>();
    return PaySummary(
      programmed: '${live['programmed_amount'] ?? '0'}',
      earned: '${live['earned_unpaid_amount'] ?? '0'}',
      paid: '${live['paid_amount'] ?? '0'}',
      sessions: ((live['sessions'] as Map?) ?? const {}).cast<String, dynamic>(),
    );
  }

  final String programmed;
  final String earned;
  final String paid;
  final Map<String, dynamic> sessions;
}

const _relationshipsFr = {
  'FATHER': 'Père',
  'MOTHER': 'Mère',
  'LEGAL_GUARDIAN': 'Tuteur légal',
  'TUTOR': 'Tuteur',
  'OTHER': 'Autre',
};

/// Labels in the CURRENT language (French source: [_relationshipsFr]).
Map<String, String> get relationships => trMap(_relationshipsFr);

/// A verified parent of one of my pupils, as offered by the server.
class ParentContact {
  ParentContact({required this.member, required this.name, required this.relationship});

  factory ParentContact.fromJson(Map<String, dynamic> json) => ParentContact(
    member: '${json['member']}',
    name: (json['name'] as String?) ?? '',
    relationship: (json['relationship'] as String?) ?? '',
  );

  final String member;
  final String name;
  final String relationship;

  String get relationshipLabel => relationships[relationship] ?? relationship;
}

/// A pupil I teach now and the parents I may write to about him or her.
class PupilContacts {
  PupilContacts({required this.student, required this.name, required this.parents});

  factory PupilContacts.fromJson(Map<String, dynamic> json) => PupilContacts(
    student: '${json['student']}',
    name: (json['name'] as String?) ?? '',
    parents: ((json['parents'] as List?) ?? const [])
        .map((p) => ParentContact.fromJson((p as Map).cast<String, dynamic>()))
        .toList(),
  );

  final String student;
  final String name;
  final List<ParentContact> parents;
}
