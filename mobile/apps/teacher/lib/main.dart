import 'package:flutter/material.dart';
import 'package:intl/date_symbol_data_local.dart';
import 'package:school_core/school_core.dart';

import 'app.dart';
import 'data/teacher_repository.dart';

/// Backend address, given at build time (never hard-coded credentials):
///   flutter run --dart-define=API_URL=http://127.0.0.1:8001/api/v1/   (USB + adb reverse)
/// Default: the host machine as seen from the Android emulator.
const apiUrl = String.fromEnvironment('API_URL', defaultValue: 'http://10.0.2.2:8000/api/v1/');

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await initializeDateFormatting('fr_FR');
  final api = ApiClient(baseUrl: apiUrl);
  final auth = AuthService(
    api,
    SecureTokenStore(prefix: 'school_managing.teacher'),
    requiredRole: 'TEACHER',
    device: const DeviceInfo(name: 'Application enseignant'),
  );
  runApp(
    TeacherApp(
      auth: auth,
      repository: TeacherRepository(api),
      realtime: () => RealtimeClient(api, socketUri(apiUrl), refresh: auth.refreshSession),
    ),
  );
  await auth.restore();
}
