import 'package:http/http.dart' as http;
import 'package:school_core/school_core.dart';

import 'app.dart';
import 'data/teacher_repository.dart';

/// The whole client graph of the app for ONE server (school_core ServerHost):
/// a server switch leaves this session and builds a new one — nothing of the
/// old school (token, identity, data, live connection) is reused.
ServerSession teacherSession(AppConfig config, {http.Client? client, TokenStore? tokens, ChannelFactory? channels}) {
  final api = ApiClient(baseUrl: config.apiUrl, client: client);
  final auth = AuthService(
    api,
    tokens ?? SecureTokenStore(prefix: 'school_managing.teacher'),
    requiredRole: 'TEACHER',
    device: const DeviceInfo(name: 'Application enseignant'),
  );
  RealtimeClient live() => channels == null
      ? RealtimeClient(api, config.socket, refresh: auth.refreshSession)
      : RealtimeClient(api, config.socket, refresh: auth.refreshSession, channelFactory: channels);
  return ServerSession(
    app: TeacherApp(auth: auth, repository: TeacherRepository(api), realtime: live),
    onReady: auth.restore, // no request before Android 17 lets the app reach the LAN
    leave: () async {
      await auth.leaveServer(); // server logout if it still answers; local session dropped anyway
    },
  );
}
