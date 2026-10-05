/// REAL backend journey of a parent (opt-in). Uses the same services as the
/// app (school_core + ParentRepository) against a running TEST backend; the
/// school's decisions go through the EXISTING admin API:
///
///   registration -> pending account -> approval by the school -> link request
///   (pupil number + birth date + ID document) -> identity mismatch then match
///   -> pupil's designation -> approval (finance visible, payment NOT granted)
///   -> home (child, class, year) -> attendance -> planning -> finance -> report
///   card (provisional hidden, validated visible + PDF) -> notification ->
///   messages (administration, teacher) -> isolation (another pupil = 404) ->
///   live WebSocket -> logout -> old token refused
///
/// Prepare the data with backend/tools/e2e_parent_fixture.py on the test
/// container, then:
///   PARENT_LIVE_URL=http://127.0.0.1:8001/api/v1/ PARENT_LIVE='(json printed by the fixture)'
///   PARENT_LIVE_ADMIN=e2eadmin PARENT_LIVE_ADMIN_PASSWORD=(generated for the run)
///   flutter test test/live_test.dart
/// The parent's password is generated here, used, and never written anywhere.
@Tags(['live'])
library;

import 'dart:convert';
import 'dart:io';
import 'dart:math';

import 'package:flutter_test/flutter_test.dart';
import 'package:school_core/school_core.dart';
import 'package:school_parent/data/parent_repository.dart';

void main() {
  final env = Platform.environment;
  final url = env['PARENT_LIVE_URL'];
  final raw = env['PARENT_LIVE'];
  final skip = url == null || raw == null || env['PARENT_LIVE_ADMIN_PASSWORD'] == null
      ? 'PARENT_LIVE_URL / PARENT_LIVE / PARENT_LIVE_ADMIN_PASSWORD not set (opt-in live test)'
      : null;

  test(
    'parent journey against the real backend',
    () async {
      final data = (jsonDecode(raw!) as Map).cast<String, dynamic>();
      final random = Random.secure();
      String token(int n) => List.generate(n, (_) => random.nextInt(36).toRadixString(36)).join();
      final password = 'Par-${token(12)}-26!';
      final email = 'parent.${token(6)}@e2e.test';

      // The school (administration) — its own session.
      final admin = ApiClient(baseUrl: url!);
      final adminAuth = AuthService(admin, MemoryTokenStore(), device: const DeviceInfo(name: 'E2E admin'));
      await adminAuth.login(env['PARENT_LIVE_ADMIN'] ?? 'e2eadmin', env['PARENT_LIVE_ADMIN_PASSWORD']!);

      // The parent — exactly the app's services.
      final api = ApiClient(baseUrl: url);
      final auth = AuthService(
        api,
        MemoryTokenStore(),
        requiredRole: 'PARENT',
        allowPending: true,
        device: const DeviceInfo(name: 'Test live parent'),
      );
      final repo = ParentRepository(api);

      // 1. Registration: weak password refused by the server's rules; then accepted.
      final weak = await _caught(
        repo.register(
          firstName: 'Awa',
          lastName: 'E2E',
          email: email,
          password: '123',
          schoolCode: data['school_code'],
        ),
      );
      expect((weak as ApiException).fieldErrors['password'], isNotEmpty);
      await repo.register(
        firstName: 'Awa',
        lastName: 'E2E',
        email: email,
        password: password,
        schoolCode: data['school_code'],
      );

      // 2. Login while PENDING: only the registration is visible.
      await auth.login(email, password);
      expect(auth.status, AuthStatus.pending);
      expect((await repo.registrations()).single.status, 'PENDING');
      expect(await _caught(repo.children()), isA<ForbiddenException>());

      // 3. The school approves the account.
      final pending = await admin.page('admin/registrations/', params: {'status': 'PENDING', 'search': email});
      await admin.post('admin/registrations/${pending.rows.single['id']}/approve/');
      await auth.reloadIdentity();
      expect(auth.status, AuthStatus.signedIn);
      expect(await repo.children(), isEmpty); // no child before a VERIFIED link

      // 4. Link request: wrong birth date -> same answer as an unknown pupil; then the right one.
      final wrong = await _caught(
        repo.requestLink(
          studentNumber: data['student_number'],
          dateOfBirth: DateTime(2010, 1, 1),
          relationship: 'MOTHER',
          documentType: 'CNI',
          documentNumber: 'CM 7788-9900',
        ),
      );
      expect((wrong as ApiException).rule, 'student_not_found');
      final request = await repo.requestLink(
        studentNumber: data['student_number'],
        dateOfBirth: DateTime.parse(data['date_of_birth']),
        relationship: 'MOTHER',
        documentType: 'CNI',
        documentNumber: 'CM 7788-9900',
      );
      expect((request.status, request.identityStatus), ('PENDING', 'PENDING'));
      expect(await repo.children(), isEmpty); // a request grants nothing

      // 5. The school checks the ORIGINAL document, records the pupil's designation, approves.
      final linkUrl = 'admin/link-requests/${request.id}/';
      final mismatch = await _caught(
        admin.post('${linkUrl}verify-identity/', body: {'document_type': 'CNI', 'document_number': 'CM 0000-0000'}),
      );
      expect((mismatch as ApiException).rule, 'identity_mismatch');
      final early = await _caught(admin.post('${linkUrl}approve/'));
      expect((early as ApiException).rule, 'identity_not_verified');
      await admin.post('${linkUrl}verify-identity/', body: {'document_type': 'CNI', 'document_number': 'cm77889900'});
      await admin.post('${linkUrl}student-approval/', body: {'decision': 'APPROVED', 'note': 'Confirmé en classe'});
      await admin.post('${linkUrl}approve/', body: {'can_view_financial_data': true, 'can_pay': false});

      // 6. Home: the child, the class, the year.
      final children = await repo.children();
      expect(children.map((c) => c.id), [data['child_id']]);
      final child = children.single;
      expect(child.className, data['class_name']);
      expect((child.canViewFinance, child.canPay), (true, false));

      // 7. Attendance (computed by the server) + gate scans (never who scanned).
      final attendance = await repo.attendance(child.id);
      expect(attendance.unexcused, isNotEmpty);
      await repo.scans(child.id);

      // 8. Planning of the class today.
      final now = DateTime.now();
      final today = DateTime(now.year, now.month, now.day);
      final sessions = await repo.sessions(child.id, today, today);
      expect(sessions, hasLength(2));
      expect(sessions.every((s) => s.schoolClass.label == data['class_name']), isTrue);

      // 9. Finance: amounts from the server; the right to pay is the server's answer.
      final obligations = await repo.obligations(child.id);
      expect(obligations.balanceDue, '75000.00');
      expect(obligations.canPay, isFalse);
      expect((await repo.invoices(child.id)).single.total, '75000.00');

      // 10. Report card: a provisional card stays hidden; the validated one is visible, with its PDF.
      final generated = await admin.post(
        'report-cards/generate/',
        body: {'school_class': data['class_id'], 'academic_period': data['period_id']},
      );
      final card = (generated as List).cast<Map>().firstWhere((c) => c['student'] == child.id);
      expect(await repo.reportCards(child.id), isEmpty); // provisional: never for a parent
      await admin.post('report-cards/${card['id']}/validate/');
      final cards = await repo.reportCards(child.id);
      expect(cards.single.status, 'VALIDATED');
      final pdf = await repo.reportCardPdf(cards.single.id);
      expect(ascii.decode(pdf.sublist(0, 5)), '%PDF-');

      // 11. Notification of the validated report card.
      final notifications = await repo.notifications();
      expect(notifications.map((n) => n.type), contains('REPORT_CARD'));

      // 12. Messages: the administration, then a teacher of my child.
      final toSchool = await repo.startConversation(
        type: 'ADMINISTRATION',
        title: 'Question E2E',
        body: 'Bonjour, une question.',
        clientId: newClientId(),
      );
      expect((await repo.messages(toSchool.id)).single.body, 'Bonjour, une question.');
      final teachers = await repo.teachers(child.id);
      expect(teachers.map((t) => t.member), [data['teacher_member']]);
      await repo.startConversation(
        type: 'PARENT_TEACHER',
        participants: [teachers.single.member],
        student: child.id,
        body: 'Bonjour, les devoirs ?',
        clientId: newClientId(),
      );

      // 13. Isolation: another pupil of the same class is a 404 everywhere.
      final other = data['other_student_id'] as String;
      expect(await _caught(repo.attendance(other)), isA<NotFoundException>());
      expect(await _caught(repo.sessions(other, today, today)), isA<NotFoundException>());
      expect(await _caught(repo.obligations(other)), isA<NotFoundException>());
      expect(await _caught(repo.teachers(other)), isA<NotFoundException>());
      expect(await repo.reportCards(other), isEmpty);

      // 14. Live WebSocket (existing ws/v1/realtime/).
      final realtime = RealtimeClient(api, AppConfig.parse(apiUrl: url).socket, refresh: auth.refreshSession);
      final online = realtime.states.firstWhere((s) => s == RealtimeState.online).timeout(const Duration(seconds: 10));
      realtime.start();
      expect(await online, RealtimeState.online);
      await realtime.dispose();

      // 15. Logout: the old token is refused.
      final oldAccess = api.accessToken;
      await auth.logout();
      api.accessToken = oldAccess;
      expect(await _caught(repo.children()), isA<UnauthorizedException>());
      await adminAuth.logout();
    },
    skip: skip,
    timeout: const Timeout(Duration(minutes: 3)),
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
