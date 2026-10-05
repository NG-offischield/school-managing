/// Everything the teacher app reads or does, through the EXISTING API only.
/// The server decides what this teacher may see: no teacher id is ever sent
/// to choose whose data to read ("my" endpoints and server-side visibility).
///
///   GET  /courses/                          own courses (server visibility)
///   GET  /teacher/sessions/?date_from&date_to   sessions taught or planned
///   GET  /sessions/{id}/                    one of them (404 otherwise)
///   GET  /planning/changes/?session=        changes concerning me
///   POST /teacher/sessions/{id}/check-in/   self-declared presence (verified later)
///   GET  /teacher/payroll/?date_from&date_to    own remuneration (live)
///   GET  /notifications/ …/unread-count/   POST …/{id}/read/  …/read-all/
///   GET  /conversations/ …/{id}/messages/  POST …/messages/  …/read/
///   GET  /complaints/                       complaints visible to me
library;

import 'dart:math';

import 'package:intl/intl.dart';
import 'package:school_core/school_core.dart';

import '../models/models.dart';

final _day = DateFormat('yyyy-MM-dd');

class TeacherRepository {
  TeacherRepository(this.api);

  final ApiClient api;

  Future<List<Course>> courses() async =>
      (await api.listAll('courses/', params: {'status': 'active'})).map(Course.fromJson).toList();

  Future<List<TeachingSession>> sessions(DateTime from, DateTime to) async {
    final rows = await api.listAll(
      'teacher/sessions/',
      params: {'date_from': _day.format(from), 'date_to': _day.format(to)},
    );
    final sessions = rows.map(TeachingSession.fromJson).toList()
      ..sort((a, b) => (a.start ?? DateTime(0)).compareTo(b.start ?? DateTime(0)));
    return sessions;
  }

  Future<TeachingSession> session(String id) async =>
      TeachingSession.fromJson((await api.get('sessions/$id/') as Map).cast<String, dynamic>());

  Future<List<ScheduleChangeItem>> changes(String sessionId) async => (await api.listAll(
    'planning/changes/',
    params: {'session': sessionId},
  )).map(ScheduleChangeItem.fromJson).toList();

  /// Self-declared presence (PRESENT / ABSENT). The administration validates
  /// it later; the server refuses before the start or once verified.
  Future<String> checkIn(String sessionId, String status) async {
    final data = await api.post('teacher/sessions/$sessionId/check-in/', body: {'status': status}) as Map;
    return '${data['self_reported_status']}';
  }

  Future<PaySummary> pay(DateTime from, DateTime to) async => PaySummary.fromJson(
    (await api.get('teacher/payroll/', params: {'date_from': _day.format(from), 'date_to': _day.format(to)}) as Map)
        .cast<String, dynamic>(),
  );

  // --- communication ---------------------------------------------------------------

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

  /// One client_id per message intent: a resend after a network failure is
  /// recognised by the server (no duplicate).
  Future<ChatMessage> send(String conversationId, String body, {required String clientId, String? myName}) async {
    final data = await api.post('conversations/$conversationId/messages/', body: {'body': body, 'client_id': clientId});
    return ChatMessage.fromJson((data as Map).cast<String, dynamic>(), myName: myName);
  }

  Future<void> markConversationRead(String conversationId) => api.post('conversations/$conversationId/read/');

  Future<List<Complaint>> complaints() async => (await api.listAll('complaints/')).map(Complaint.fromJson).toList();
}

String newClientId() {
  final random = Random.secure();
  return List.generate(16, (_) => random.nextInt(256).toRadixString(16).padLeft(2, '0')).join();
}
