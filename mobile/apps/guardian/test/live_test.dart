/// REAL backend journey of a guardian (opt-in), with the app's services:
///
///   account activation (code issued by the school) -> login -> scan at the
///   gate (the server's answer) -> MY scans only (never another guardian's)
///   -> notifications -> communication allowed to the role (no messaging,
///   spec §8) -> nothing else reachable -> live WebSocket -> logout -> old
///   token refused
///
/// Prepare the data with backend/tools/e2e_field_fixture.py on the test
/// container, then:
///   FIELD_LIVE_URL=http://127.0.0.1:8001/api/v1/ FIELD_LIVE='(json printed by the fixture)'
///   FIELD_LIVE_ADMIN=e2eadmin FIELD_LIVE_ADMIN_PASSWORD=(generated for the run)
///   flutter test test/live_test.dart
@Tags(['live'])
library;

import 'dart:convert';
import 'dart:io';
import 'dart:math';

import 'package:flutter_test/flutter_test.dart';
import 'package:school_core/school_core.dart';
import 'package:school_guardian/data/guardian_repository.dart';

void main() {
  final env = Platform.environment;
  final url = env['FIELD_LIVE_URL'];
  final raw = env['FIELD_LIVE'];
  final skip = url == null || raw == null || env['FIELD_LIVE_ADMIN_PASSWORD'] == null
      ? 'FIELD_LIVE_URL / FIELD_LIVE / FIELD_LIVE_ADMIN_PASSWORD not set (opt-in live test)'
      : null;

  test(
    'guardian journey against the real backend',
    () async {
      final data = (jsonDecode(raw!) as Map).cast<String, dynamic>();
      final random = Random.secure();
      final password = 'Gar-${List.generate(12, (_) => random.nextInt(36).toRadixString(36)).join()}-26!';

      final admin = ApiClient(baseUrl: url!);
      final adminAuth = AuthService(admin, MemoryTokenStore(), device: const DeviceInfo(name: 'E2E admin'));
      await adminAuth.login(env['FIELD_LIVE_ADMIN'] ?? 'e2eadmin', env['FIELD_LIVE_ADMIN_PASSWORD']!);
      final issued = await admin.post('admin/accounts/${data['guardian_member']}/activation/') as Map;

      final api = ApiClient(baseUrl: url);
      final auth = AuthService(api, MemoryTokenStore(), requiredRole: 'GUARDIAN');
      final repo = GuardianRepository(api);

      // 1. Activation then login.
      expect(await auth.completeActivation('${issued['code']}', password), data['guardian_login']);
      await auth.login(data['guardian_login'], password);
      expect(auth.identity!.hasRole('GUARDIAN'), isTrue);

      // 2. Scan at the gate: the server's answer (solvency status only, never an amount).
      final outcome = await repo.gate.scan(data['pupil_token']);
      expect(outcome.accepted, isTrue, reason: outcome.result);
      expect(outcome.studentName, data['pupil_name']);
      expect(outcome.className, data['class_name']);
      expect(['UP_TO_DATE', 'OVERDUE'], contains(outcome.solvency));
      final again = await repo.gate.scan(data['pupil_token']);
      expect(again.result, 'ALREADY_PRESENT');
      final unknown = await repo.gate.scan('pas-un-qr-${random.nextInt(9999)}');
      expect(unknown.result, 'UNKNOWN_TOKEN');

      // 3. MY scans only: another guardian's scan of today never appears.
      final mine = await repo.gate.myScans(DateTime.now());
      expect(mine, hasLength(3));
      expect(mine.map((s) => s.id), isNot(contains(data['other_guardian_scan'])));

      // 3b. The school reissues the card: the old QR is refused (revoked), the new one is read.
      final reissued =
          await admin.post(
                'admin/qr-codes/reissue/',
                body: {'student': data['pupil_id'], 'reason': 'Carte perdue (E2E)'},
              )
              as Map;
      expect((await repo.gate.scan(data['pupil_token'])).result, 'REVOKED_TOKEN');
      expect(looksLikeQrToken('${reissued['token']}'), isTrue); // what the camera accepts
      expect((await repo.gate.scan('${reissued['token']}')).result, 'ALREADY_PRESENT');

      // 4. Notifications.
      await repo.notifications();
      await repo.unreadCount();

      // 5. Communication allowed to the role: no messaging, no complaints.
      final message = await _caught(
        repo.startConversation(type: 'ADMINISTRATION', body: 'Bonjour', clientId: newClientId()),
      );
      expect(message, isA<ForbiddenException>());
      expect(
        await _caught(repo.fileComplaint(category: 'OTHER', subject: 'x', description: 'y')),
        isA<ForbiddenException>(),
      );

      // 6. Nothing else of the school: staff list, payroll, administration.
      expect(await api.listAll('staff/'), isEmpty);
      expect(await api.get('payroll/me/'), isEmpty);
      expect(await _caught(api.get('admin/scans/')), isA<ForbiddenException>());

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
      expect(await _caught(repo.gate.myScans(DateTime.now())), isA<UnauthorizedException>());
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
