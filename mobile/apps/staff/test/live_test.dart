/// REAL backend journey of a staff member (opt-in), with the app's services:
///
///   account activation (code issued by the school) -> login -> my record
///   and functions -> the school's planning today -> notifications ->
///   message to the administration -> scan (no solvency for staff) -> my
///   remuneration (another payroll = 404) -> live WebSocket -> logout -> old
///   token refused
///
/// Same preparation as the guardian's: backend/tools/e2e_field_fixture.py,
/// then FIELD_LIVE_URL / FIELD_LIVE / FIELD_LIVE_ADMIN / FIELD_LIVE_ADMIN_PASSWORD
///   flutter test test/live_test.dart
@Tags(['live'])
library;

import 'dart:convert';
import 'dart:io';
import 'dart:math';

import 'package:flutter_test/flutter_test.dart';
import 'package:school_core/school_core.dart';
import 'package:school_staff/data/staff_repository.dart';

void main() {
  final env = Platform.environment;
  final url = env['FIELD_LIVE_URL'];
  final raw = env['FIELD_LIVE'];
  final skip = url == null || raw == null || env['FIELD_LIVE_ADMIN_PASSWORD'] == null
      ? 'FIELD_LIVE_URL / FIELD_LIVE / FIELD_LIVE_ADMIN_PASSWORD not set (opt-in live test)'
      : null;

  test(
    'staff journey against the real backend',
    () async {
      final data = (jsonDecode(raw!) as Map).cast<String, dynamic>();
      final random = Random.secure();
      final password = 'Per-${List.generate(12, (_) => random.nextInt(36).toRadixString(36)).join()}-26!';

      final admin = ApiClient(baseUrl: url!);
      final adminAuth = AuthService(admin, MemoryTokenStore(), device: const DeviceInfo(name: 'E2E admin'));
      await adminAuth.login(env['FIELD_LIVE_ADMIN'] ?? 'e2eadmin', env['FIELD_LIVE_ADMIN_PASSWORD']!);
      final issued = await admin.post('admin/accounts/${data['staff_member']}/activation/') as Map;

      final api = ApiClient(baseUrl: url);
      final auth = AuthService(api, MemoryTokenStore(), requiredRole: 'STAFF');
      final repo = StaffRepository(api);

      // 1. Activation then login.
      expect(await auth.completeActivation('${issued['code']}', password), data['staff_login']);
      await auth.login(data['staff_login'], password);
      expect(auth.identity!.hasRole('STAFF'), isTrue);

      // 2. My record and functions only.
      final me = (await repo.me())!;
      expect(me.functions.map((f) => f.label), [data['staff_function']]);
      expect(await api.listAll('staff/'), hasLength(1));

      // 3. The school's planning today.
      final now = DateTime.now();
      final today = DateTime(now.year, now.month, now.day);
      final sessions = await repo.sessions(today, today);
      expect(sessions.where((s) => s.schoolClass.label == data['class_name']), hasLength(2));
      await repo.changes(since: today.subtract(const Duration(days: 7)));
      await repo.breaks();

      // 4. Notifications, message to the administration (allowed), no complaint.
      await repo.notifications();
      final conversation = await repo.startConversation(
        type: 'ADMINISTRATION',
        title: 'E2E personnel',
        body: 'Bonjour, une question.',
        clientId: newClientId(),
      );
      expect((await repo.messages(conversation.id)).single.body, 'Bonjour, une question.');
      expect(
        await _caught(repo.fileComplaint(category: 'OTHER', subject: 'x', description: 'y')),
        isA<ForbiddenException>(),
      );

      // 5. Scan: staff may scan, but never see the solvency.
      final outcome = await repo.gate.scan(data['pupil_token']);
      expect(outcome.accepted, isTrue, reason: outcome.result);
      expect(outcome.solvency, isNull);
      expect((await repo.gate.myScans(DateTime.now())).single.studentName, data['pupil_name']);

      // 6. My remuneration; any other payroll is a 404.
      final payslips = await repo.payslips();
      expect(payslips.map((p) => p.id), [data['staff_payroll']]);
      final detail = await repo.payslip(data['staff_payroll']);
      expect(detail.period, data['payroll_period']);
      expect(detail.lines.map((l) => l.id), contains('SALARY'));
      expect(await _caught(repo.payslip('00000000-0000-0000-0000-000000000000')), isA<NotFoundException>());
      expect(await _caught(api.get('admin/payroll/')), isA<ForbiddenException>());

      // 7. Live WebSocket.
      final realtime = RealtimeClient(api, AppConfig.parse(apiUrl: url).socket, refresh: auth.refreshSession);
      final online = realtime.states.firstWhere((s) => s == RealtimeState.online).timeout(const Duration(seconds: 10));
      realtime.start();
      expect(await online, RealtimeState.online);
      await realtime.dispose();

      // 8. Logout: the old token is refused.
      final oldAccess = api.accessToken;
      await auth.logout();
      api.accessToken = oldAccess;
      expect(await _caught(repo.me()), isA<UnauthorizedException>());
      await adminAuth.logout();
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
