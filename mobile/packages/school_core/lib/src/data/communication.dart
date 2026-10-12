/// Data shared by every role's app (teacher, parent; guardian and staff
/// later): value formatting and the communication module (notifications,
/// conversations, complaints) of the EXISTING API. Read models only: every
/// rule — who may write to whom, what is visible — stays on the server.
///
///   GET  /notifications/  …/unread-count/   POST …/{id}/read/  …/read-all/
///   GET  /conversations/ …/{id}/messages/  POST …/messages/  …/read/
///   POST /conversations/ {conversation_type, participants, student, title, body, client_id}
///   GET  /complaints/    POST /complaints/ {category, subject, description, student, submit}
///   forum: GET /forum/spaces/  GET/POST /forum/threads/  GET/POST /forum/threads/{id}/posts/  (forum.dart)
///   plans: GET /plans/  GET /plans/{id}/  GET /plans/{id}/file/  (school_plans.dart)
library;

import 'dart:math';
import 'dart:typed_data';

import '../api/api_client.dart';
import 'forum.dart';
import 'school_plans.dart';

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
    if (i > 0 && (digits.length - i) % 3 == 0) buffer.write(' '); // narrow no-break space
    buffer.write(digits[i]);
  }
  final decimals = parts.length > 1 && parts[1].replaceAll('0', '').isNotEmpty ? ',${parts[1]}' : '';
  return '${negative ? '−' : ''}$buffer$decimals $currency'.trim();
}

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

const notificationTypes = {
  'ATTENDANCE_LATE': 'Retard',
  'ATTENDANCE_ABSENT': 'Absence',
  'CONVOCATION': 'Convocation',
  'SCHEDULE_CHANGE': 'Planning',
  'SUBSTITUTION': 'Remplacement',
  'PAYMENT': 'Paiement',
  'REFUND': 'Remboursement',
  'PAYROLL': 'Paie',
  'REPORT_CARD': 'Bulletin',
  'MESSAGE': 'Message',
  'ANNOUNCEMENT': 'Annonce',
  'COMPLAINT': 'Réclamation',
  'FORUM': 'Forum',
  'PLAN': 'Plan de l\'établissement',
};

const complaintCategories = {
  'PEDAGOGY': 'Pédagogie',
  'BEHAVIOR': 'Comportement',
  'ADMINISTRATIVE': 'Administratif',
  'FINANCE': 'Finance',
  'OTHER': 'Autre',
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
    this.payload = const {},
  });

  factory AppNotification.fromJson(Map<String, dynamic> json) => AppNotification(
    id: '${json['id']}',
    type: (json['notification_type'] as String?) ?? '',
    severity: (json['severity'] as String?) ?? 'INFO',
    title: (json['title'] as String?) ?? '',
    message: (json['message'] as String?) ?? '',
    read: json['is_read'] == true,
    at: schoolTime(json['created_at']),
    payload: ((json['payload'] as Map?) ?? const {}).cast<String, dynamic>(),
  );

  final String id;
  final String type;
  final String severity;
  final String title;
  final String message;
  final bool read;
  final DateTime? at;

  /// What the notification is about (ids decided by the server), e.g. {thread, space}.
  final Map<String, dynamic> payload;

  /// The forum thread this notification opens (announcement, forum activity).
  String? get threadId => payload['thread'] as String?;

  /// The school plan this notification opens (a published plan version).
  String? get planId => type == 'PLAN' ? payload['plan'] as String? : null;

  String get typeLabel => notificationTypes[type] ?? type;

  AppNotification markedRead() => AppNotification(
    id: id,
    type: type,
    severity: severity,
    title: title,
    message: message,
    read: true,
    at: at,
    payload: payload, // still opens its thread / plan once read
  );
}

class Conversation {
  Conversation({
    required this.id,
    required this.title,
    required this.participants,
    required this.unread,
    required this.lastMessageAt,
    this.type = '',
    this.student,
  });

  factory Conversation.fromJson(Map<String, dynamic> json) => Conversation(
    id: '${json['id']}',
    title: (json['title'] as String?) ?? '',
    participants: ((json['participants'] as List?) ?? const []).map((p) => '${(p as Map)['name']}').toList(),
    unread: (json['unread_count'] as int?) ?? 0,
    lastMessageAt: schoolTime(json['last_message_at']),
    type: (json['conversation_type'] as String?) ?? '',
    student: json['student'] as String?,
  );

  final String id;
  final String title;
  final List<String> participants;
  final int unread;
  final DateTime? lastMessageAt;
  final String type;
  final String? student;

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
    this.student,
  });

  factory Complaint.fromJson(Map<String, dynamic> json) => Complaint(
    id: '${json['id']}',
    subject: (json['subject'] as String?) ?? '',
    description: (json['description'] as String?) ?? '',
    status: (json['status'] as String?) ?? '',
    at: schoolTime(json['created_at']),
    student: json['student'] as String?,
  );

  final String id;
  final String subject;
  final String description;
  final String status;
  final DateTime? at;
  final String? student;

  String get statusLabel => complaintStatuses[status] ?? status;
}

/// One client_id per message intent: a resend after a network failure is
/// recognised by the server (no duplicate).
String newClientId() {
  final random = Random.secure();
  return List.generate(16, (_) => random.nextInt(256).toRadixString(16).padLeft(2, '0')).join();
}

/// Communication calls common to every app (the server decides visibility).
class CommunicationRepository {
  CommunicationRepository(this.api);

  final ApiClient api;

  Future<ApiPage> notificationsPage({int page = 1, bool unreadOnly = false}) =>
      api.page('notifications/', page: page, pageSize: 30, params: {'is_read': unreadOnly ? 'false' : null});

  Future<List<AppNotification>> notifications({bool unreadOnly = false}) async =>
      (await notificationsPage(unreadOnly: unreadOnly)).rows.map(AppNotification.fromJson).toList();

  Future<int> unreadCount() async => ((await api.get('notifications/unread-count/') as Map)['unread'] as int?) ?? 0;

  Future<void> markRead(String id) => api.post('notifications/$id/read/');

  Future<int> markAllRead() async => ((await api.post('notifications/read-all/') as Map)['marked'] as int?) ?? 0;

  Future<List<Conversation>> conversations() async =>
      (await api.listAll('conversations/')).map(Conversation.fromJson).toList();

  Future<List<ChatMessage>> messages(String conversationId, {String? myName}) async {
    final rows = await api.listAll('conversations/$conversationId/messages/');
    return rows.reversed.map((r) => ChatMessage.fromJson(r, myName: myName)).toList();
  }

  Future<ChatMessage> send(String conversationId, String body, {required String clientId, String? myName}) async {
    final data = await api.post('conversations/$conversationId/messages/', body: {'body': body, 'client_id': clientId});
    return ChatMessage.fromJson((data as Map).cast<String, dynamic>(), myName: myName);
  }

  Future<void> markConversationRead(String conversationId) => api.post('conversations/$conversationId/read/');

  /// New conversation (ADMINISTRATION, or PARENT_TEACHER about a pupil).
  /// The server checks who may write to whom; same client_id = same conversation.
  Future<Conversation> startConversation({
    required String type,
    List<String> participants = const [],
    String? student,
    String? title,
    required String body,
    required String clientId,
  }) async {
    final data = await api.post(
      'conversations/',
      body: {
        'conversation_type': type,
        'participants': participants,
        'student': ?student,
        if (title != null && title.trim().isNotEmpty) 'title': title.trim(),
        'body': body,
        'client_id': clientId,
      },
    );
    return Conversation.fromJson((data as Map).cast<String, dynamic>());
  }

  Future<List<Complaint>> complaints() async => (await api.listAll('complaints/')).map(Complaint.fromJson).toList();

  Future<Complaint> fileComplaint({
    required String category,
    required String subject,
    required String description,
    String? student,
  }) async {
    final data = await api.post(
      'complaints/',
      body: {
        'category': category,
        'subject': subject.trim(),
        'description': description.trim(),
        'student': ?student,
        'submit': true,
      },
    );
    return Complaint.fromJson((data as Map).cast<String, dynamic>());
  }

  // --- forum (ADR 0015): the server decides spaces, membership, locks, announcements -------------

  Future<List<ForumSpace>> forumSpaces() async => ((await api.get('forum/spaces/') as List?) ?? const [])
      .map((r) => ForumSpace.fromJson((r as Map).cast<String, dynamic>()))
      .toList();

  /// Threads, most recent activity first; [space] = one space, null = all mine.
  Future<ForumPage<ForumThread>> forumThreads({String? space, int page = 1, int pageSize = 20}) async {
    final result = await api.page('forum/threads/', page: page, pageSize: pageSize, params: {'space': space});
    return ForumPage(result.rows.map(ForumThread.fromJson).toList(), hasNext: result.hasNext, page: page);
  }

  Future<ForumThread> forumThread(String id) async =>
      ForumThread.fromJson((await api.get('forum/threads/$id/') as Map).cast<String, dynamic>());

  /// Posts in reading order (oldest first).
  Future<ForumPage<ForumPost>> forumPosts(String threadId, {int page = 1, int pageSize = 30}) async {
    final result = await api.page('forum/threads/$threadId/posts/', page: page, pageSize: pageSize);
    return ForumPage(result.rows.map(ForumPost.fromJson).toList(), hasNext: result.hasNext, page: page);
  }

  Future<ForumThread> createForumThread({required String space, required String title, required String body}) async =>
      ForumThread.fromJson(
        (await api.post('forum/threads/', body: {'space': space, 'title': title.trim(), 'body': body.trim()}) as Map)
            .cast<String, dynamic>(),
      );

  Future<ForumPost> replyForum(String threadId, String body) async => ForumPost.fromJson(
    (await api.post('forum/threads/$threadId/posts/', body: {'body': body.trim()}) as Map).cast<String, dynamic>(),
  );

  /// Removes MY post (the server refuses anybody else's: moderation is the administration's).
  Future<ForumPost> deleteForumPost(String postId) async => ForumPost.fromJson(
    ((await api.request('DELETE', 'forum/posts/$postId/', body: const {})).data as Map).cast<String, dynamic>(),
  );

  // --- school plans: the server re-checks the audience at every request (404 otherwise) ----------

  Future<List<SchoolPlan>> plans() async => ((await api.get('plans/') as List?) ?? const [])
      .map((r) => SchoolPlan.fromJson((r as Map).cast<String, dynamic>()))
      .toList();

  Future<SchoolPlan> plan(String id) async =>
      SchoolPlan.fromJson((await api.get('plans/$id/') as Map).cast<String, dynamic>());

  /// Bytes of the plan's published version (never an older or draft one).
  Future<Uint8List> planFile(String id) => api.download('plans/$id/file/');
}
