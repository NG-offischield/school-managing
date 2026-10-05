/// REAL backend journey of a teacher (opt-in). Uses the same services as the
/// app (school_core + TeacherRepository) against a running TEST backend:
///
///   activation -> login -> dashboard data -> planning -> session (check-in,
///   changes) -> notifications -> isolation (B's data is a 404) -> live
///   WebSocket -> logout -> old token refused -> re-login -> code not reusable
///
/// Prepare the data with mobile/tools/prepare_live_teacher.py, then:
///   TEACHER_LIVE_URL=http://127.0.0.1:8001/api/v1/ TEACHER_LIVE='(json printed by the script)'
///   flutter test test/live_test.dart
/// The new password is generated here, used once, and never written anywhere.
@Tags(['live'])
library;

import 'dart:convert';
import 'dart:io';
import 'dart:math';

import 'package:flutter_test/flutter_test.dart';
import 'package:school_core/school_core.dart';
import 'package:school_teacher/data/teacher_repository.dart';

void main() {
  final url = Platform.environment['TEACHER_LIVE_URL'];
  final raw = Platform.environment['TEACHER_LIVE'];
  final skip = url == null || raw == null ? 'TEACHER_LIVE_URL / TEACHER_LIVE not set (opt-in live test)' : null;

  test(
    'teacher journey against the real backend',
    () async {
      final data = (jsonDecode(raw!) as Map).cast<String, dynamic>();
      final random = Random.secure();
      final password = 'Mob-${List.generate(12, (_) => random.nextInt(36).toRadixString(36)).join()}-26!';
      final api = ApiClient(baseUrl: url!);
      final store = MemoryTokenStore();
      final auth = AuthService(
        api,
        store,
        requiredRole: 'TEACHER',
        device: const DeviceInfo(name: 'Test live'),
      );
      final repo = TeacherRepository(api);

      // 1. Activation (public endpoints) — then the normal login.
      final preview = await auth.checkActivation('${data['code']}'.toLowerCase());
      expect(preview.login, data['login']);
      final weak = await _caught(auth.completeActivation('${data['code']}', '123'));
      expect((weak as ApiException).fieldErrors['password'], isNotEmpty); // the server's password rules
      expect(await auth.completeActivation('${data['code']}', password), data['login']);
      await auth.login('${data['login']}', password);
      expect(auth.status, AuthStatus.signedIn);
      expect(auth.identity!.hasRole('TEACHER'), isTrue);

      // 2. Dashboard data: only mine.
      final today = DateTime.now();
      final day = DateTime(today.year, today.month, today.day);
      final courses = await repo.courses();
      expect(courses.map((c) => c.className), [data['course_a_class']]);
      final week = await repo.sessions(
        day.subtract(Duration(days: today.weekday - 1)),
        day.add(const Duration(days: 7)),
      );
      final myName = auth.identity!.fullName;
      expect(week, isNotEmpty);
      for (final session in week) {
        expect(
          session.teacher.label == myName || session.plannedTeacher.label == myName,
          isTrue,
          reason: session.title,
        );
      }
      expect(week.any((s) => s.id == data['b_only_session']), isFalse);
      final replaced = week.firstWhere((s) => s.id == data['substituted_session']);
      expect(replaced.substituted && replaced.teacher.label == myName, isTrue);

      // 3. Planning today + session detail, changes, self check-in.
      final todays = await repo.sessions(day, day);
      expect(todays.any((s) => s.id == data['started_session']), isTrue);
      final started = await repo.session('${data['started_session']}');
      expect(started.schoolClass.label, data['course_a_class']);
      expect(await repo.checkIn(started.id, 'PRESENT'), 'PRESENT');
      final changes = await repo.changes('${data['substituted_session']}');
      expect(changes.map((c) => c.type), contains('TEACHER_SUBSTITUTED'));

      // 4. Isolation: B's own session is not visible to A (404, like a missing id).
      expect(await _caught(repo.session('${data['b_only_session']}')), isA<NotFoundException>());

      // 5. Notifications (the substitution) + read.
      final unread = await repo.unreadCount();
      expect(unread, greaterThan(0));
      final notifications = await repo.notifications();
      final substitution = notifications.firstWhere((n) => n.type == 'SUBSTITUTION' || n.type == 'SCHEDULE_CHANGE');
      await repo.markRead(substitution.id);
      expect(await repo.unreadCount(), unread - 1);

      // 6. Live WebSocket (existing ws/v1/realtime/).
      final realtime = RealtimeClient(api, socketUri(url), refresh: auth.refreshSession);
      final online = realtime.states.firstWhere((s) => s == RealtimeState.online).timeout(const Duration(seconds: 10));
      realtime.start();
      expect(await online, RealtimeState.online);
      await realtime.dispose();

      // 7. Logout, old token refused, re-login, refresh.
      final oldAccess = api.accessToken;
      await auth.logout();
      api.accessToken = oldAccess;
      expect(await _caught(repo.courses()), isA<UnauthorizedException>());
      api.accessToken = null;
      await auth.login('${data['login']}', password);
      expect(auth.status, AuthStatus.signedIn);
      final again = AuthService(api, store, requiredRole: 'TEACHER');
      await again.restore(); // refresh with the stored token
      expect(again.status, AuthStatus.signedIn);
      await again.logout();

      // 8. The activation code cannot be reused.
      final reused = await _caught(auth.completeActivation('${data['code']}', '$password-x'));
      expect((reused as ApiException).code, 'INVALID_ACTIVATION_CODE');
    },
    skip: skip,
    timeout: const Timeout(Duration(minutes: 2)),
  );
}

Future<Object?> _caught(Future<Object?> future) async {
  try {
    await future;
    return null;
  } on Object catch (error) {
    return error;
  }
}
