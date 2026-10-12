import 'package:http/http.dart' as http;
import 'package:school_core/school_core.dart';

import 'app.dart';
import 'data/parent_repository.dart';
import 'data/pdf_store.dart';

/// The whole client graph of the app for ONE server (school_core ServerHost):
/// a server switch leaves this session and builds a new one — nothing of the
/// old school (token, identity, data, live connection) is reused.
ServerSession parentSession(
  AppConfig config, {
  http.Client? client,
  TokenStore? tokens,
  ChannelFactory? channels,
  PdfStore pdfStore = const DevicePdfStore(),
  PlanFiles planFiles = const DevicePlanFiles(),
}) {
  final api = ApiClient(baseUrl: config.apiUrl, client: client);
  final auth = AuthService(
    api,
    tokens ?? SecureTokenStore(prefix: 'school_managing.parent'),
    requiredRole: 'PARENT',
    allowPending: true, // a self-registered parent waits for the school's approval
    device: DeviceInfo(name: tr('Application parent')),
  );
  RealtimeClient live() => channels == null
      ? RealtimeClient(api, config.socket, refresh: auth.refreshSession)
      : RealtimeClient(api, config.socket, refresh: auth.refreshSession, channelFactory: channels);
  return ServerSession(
    app: ParentApp(
      auth: auth,
      repository: ParentRepository(api),
      pdfStore: pdfStore,
      planFiles: planFiles,
      realtime: live,
    ),
    onReady: auth.restore, // no request before Android 17 lets the app reach the LAN
    leave: () async {
      await auth.leaveServer(); // server logout if it still answers; local session dropped anyway
      await pdfStore.clear(); // receipts / report cards of the old school
      await planFiles.clear(); // its school plans handed to the PDF viewer
    },
  );
}
