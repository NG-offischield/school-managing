import 'package:flutter/material.dart';
import 'package:intl/date_symbol_data_local.dart';
import 'package:school_core/school_core.dart';

import 'app.dart';
import 'data/parent_repository.dart';
import 'data/pdf_store.dart';

/// Backend address, given at build time — never written in the sources
/// (school_core AppConfig, docs/reseau-local.md):
///   flutter run --dart-define-from-file=../../config/lan.json
///   `flutter run --dart-define=API_URL=http://<IPv4 du PC>:8000/api/v1/`   (optional WS_URL)
Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await initializeDateFormatting('fr_FR');
  final AppConfig config;
  try {
    config = AppConfig.fromEnvironment();
  } on AppConfigException catch (error) {
    return runApp(ConfigErrorApp(error.message));
  }
  final api = ApiClient(baseUrl: config.apiUrl);
  final auth = AuthService(
    api,
    SecureTokenStore(prefix: 'school_managing.parent'),
    requiredRole: 'PARENT',
    allowPending: true, // a self-registered parent waits for the school's approval
    device: const DeviceInfo(name: 'Application parent'),
  );
  runApp(
    LocalNetworkGate(
      config: config,
      onReady: auth.restore, // no request before Android 17 lets the app reach the LAN
      child: ParentApp(
        auth: auth,
        repository: ParentRepository(api),
        pdfStore: const DevicePdfStore(),
        realtime: () => RealtimeClient(api, config.socket, refresh: auth.refreshSession),
      ),
    ),
  );
}
