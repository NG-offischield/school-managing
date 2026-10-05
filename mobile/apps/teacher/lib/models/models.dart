/// Data of the teacher app, as returned by the API (read models only:
/// every rule stays on the server).
library;

/// Server datetimes carry the school's offset ("2026-10-05T08:00:00+01:00"):
/// the wall-clock part is shown as is — the school's time, whatever the
/// phone's time zone.
DateTime? schoolTime(Object? iso) {
  final text = iso as String?;
  if (text == null || text.length < 16) return null;
  return DateTime.tryParse(text.substring(0, 19.clamp(0, text.length)));
}

/// "15000.00", "XAF" -> "15 000 XAF" (amounts travel as strings; never doubles).
String formatMoney(Object? amount, [String currency = 'XAF']) {
  final text = '${amount ?? '0'}';
  final negative = text.startsWith('-');
  final parts = text.replaceFirst('-', '').split('.');
  final digits = parts.first;
  final buffer = StringBuffer();
  for (var i = 0; i < digits.length; i++) {
    if (i > 0 && (digits.length - i) % 3 == 0) buffer.write(' ');
    buffer.write(digits[i]);
  }
  final decimals = parts.length > 1 && parts[1].replaceAll('0', '').isNotEmpty ? ',${parts[1]}' : '';
  return '${negative ? '−' : ''}$buffer$decimals $currency'.trim();
}

const sessionStatuses = {'SCHEDULED': 'Prévue', 'COMPLETED': 'Réalisée', 'CANCELLED': 'Annulée'};

class Ref {
  const Ref(this.id, this.label, [this.extra = '']);

  factory Ref.of(Object? json, String labelKey, [String extraKey = '']) {
    final map = (json as Map?)?.cast<String, dynamic>() ?? const {};
    return Ref('${map['id'] ?? ''}', '${map[labelKey] ?? ''}', extraKey.isEmpty ? '' : '${map[extraKey] ?? ''}');
  }

  final String id;
  final String label;
  final String extra;
}

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

  static const labels = {
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

const notificationTypes = {
  'SCHEDULE_CHANGE': 'Planning',
  'SUBSTITUTION': 'Remplacement',
  'PAYROLL': 'Paie',
  'MESSAGE': 'Message',
  'ANNOUNCEMENT': 'Annonce',
  'COMPLAINT': 'Réclamation',
  'PAYMENT': 'Paiement',
};

class AppNotification {
  AppNotification({
    required this.id,
    required this.type,
    required this.severity,
    required this.title,
    required this.message,
    required this.read,
    required this.at,
  });

  factory AppNotification.fromJson(Map<String, dynamic> json) => AppNotification(
    id: '${json['id']}',
    type: (json['notification_type'] as String?) ?? '',
    severity: (json['severity'] as String?) ?? 'INFO',
    title: (json['title'] as String?) ?? '',
    message: (json['message'] as String?) ?? '',
    read: json['is_read'] == true,
    at: schoolTime(json['created_at']),
  );

  final String id;
  final String type;
  final String severity;
  final String title;
  final String message;
  final bool read;
  final DateTime? at;

  String get typeLabel => notificationTypes[type] ?? type;

  AppNotification markedRead() =>
      AppNotification(id: id, type: type, severity: severity, title: title, message: message, read: true, at: at);
}

class Conversation {
  Conversation({
    required this.id,
    required this.title,
    required this.participants,
    required this.unread,
    required this.lastMessageAt,
  });

  factory Conversation.fromJson(Map<String, dynamic> json) => Conversation(
    id: '${json['id']}',
    title: (json['title'] as String?) ?? '',
    participants: ((json['participants'] as List?) ?? const []).map((p) => '${(p as Map)['name']}').toList(),
    unread: (json['unread_count'] as int?) ?? 0,
    lastMessageAt: schoolTime(json['last_message_at']),
  );

  final String id;
  final String title;
  final List<String> participants;
  final int unread;
  final DateTime? lastMessageAt;

  String get label => title.isNotEmpty ? title : participants.join(', ');
}

class ChatMessage {
  ChatMessage({
    required this.id,
    required this.conversation,
    required this.sender,
    required this.body,
    required this.at,
    required this.attachments,
    this.mine = false,
  });

  factory ChatMessage.fromJson(Map<String, dynamic> json, {String? myName}) => ChatMessage(
    id: '${json['id']}',
    conversation: '${json['conversation']}',
    sender: (json['sender_name'] as String?) ?? '',
    body: json['body'] as String?,
    at: schoolTime(json['created_at']),
    attachments: ((json['attachments'] as List?) ?? const []).map((a) => '${(a as Map)['name']}').toList(),
    mine: myName != null && json['sender_name'] == myName,
  );

  final String id;
  final String conversation;
  final String sender;
  final String? body;
  final DateTime? at;
  final List<String> attachments;
  final bool mine;
}

const complaintStatuses = {
  'DRAFT': 'Brouillon',
  'OPEN': 'Ouverte',
  'IN_PROGRESS': 'En traitement',
  'RESOLVED': 'Résolue',
  'CANCELLED': 'Annulée',
  'CLOSED': 'Clôturée',
};

class Complaint {
  Complaint({
    required this.id,
    required this.subject,
    required this.description,
    required this.status,
    required this.at,
  });

  factory Complaint.fromJson(Map<String, dynamic> json) => Complaint(
    id: '${json['id']}',
    subject: (json['subject'] as String?) ?? '',
    description: (json['description'] as String?) ?? '',
    status: (json['status'] as String?) ?? '',
    at: schoolTime(json['created_at']),
  );

  final String id;
  final String subject;
  final String description;
  final String status;
  final DateTime? at;

  String get statusLabel => complaintStatuses[status] ?? status;
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
