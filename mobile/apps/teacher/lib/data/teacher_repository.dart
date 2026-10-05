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
///   communication (notifications, conversations, complaints): CommunicationRepository (school_core)
library;

import 'package:intl/intl.dart';
import 'package:school_core/school_core.dart';

import '../models/models.dart';

final _day = DateFormat('yyyy-MM-dd');

class TeacherRepository extends CommunicationRepository {
  TeacherRepository(super.api);

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
}
