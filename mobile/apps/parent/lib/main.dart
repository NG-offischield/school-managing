import 'package:flutter/material.dart';
import 'package:intl/date_symbol_data_local.dart';
import 'package:school_core/school_core.dart';

import 'app.dart';
import 'data/parent_repository.dart';
import 'data/pdf_store.dart';

/// Backend address, given at build time (never hard-coded credentials):
///   flutter run --dart-define=API_URL=http://127.0.0.1:8000/api/v1/   (USB + adb reverse)
/// Default: the host machine as seen from the Android emulator.
const apiUrl = String.fromEnvironment('API_URL', defaultValue: 'http://10.0.2.2:8000/api/v1/');

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await initializeDateFormatting('fr_FR');
  final api = ApiClient(baseUrl: apiUrl);
  final auth = AuthService(
    api,
    SecureTokenStore(prefix: 'school_managing.parent'),
    requiredRole: 'PARENT',
    allowPending: true, // a self-registered parent waits for the school's approval
    device: const DeviceInfo(name: 'Application parent'),
  );
  runApp(
    ParentApp(
      auth: auth,
      repository: ParentRepository(api),
      pdfStore: const DevicePdfStore(),
      realtime: () => RealtimeClient(api, socketUri(apiUrl), refresh: auth.refreshSession),
    ),
  );
  await auth.restore();
}
