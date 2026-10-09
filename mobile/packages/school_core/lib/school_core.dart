/// Shared infrastructure of the School Managing mobile apps (teacher, parent,
/// guardian, staff): backend address (API_URL / WS_URL), Android 17 local
/// network permission, API client and errors, session and
/// secure token storage, activation, real time, theme, components and the
/// communication module every role shares.
/// No business rule: the Django API is the source of truth.
library;

export 'src/api/api_client.dart';
export 'src/api/api_error.dart';
export 'src/auth/auth_service.dart';
export 'src/auth/identity.dart';
export 'src/auth/token_store.dart';
export 'src/config/app_config.dart';
export 'src/config/local_network.dart';
export 'src/data/communication.dart';
export 'src/data/forum.dart';
export 'src/data/school_calendar.dart';
export 'src/messages.dart';
export 'src/realtime/realtime_client.dart';
export 'src/theme/app_theme.dart';
export 'src/ui/activation_screen.dart';
export 'src/ui/communication_screen.dart';
export 'src/ui/composers.dart';
export 'src/ui/conversation_screen.dart';
export 'src/ui/forum_screen.dart';
export 'src/ui/gate.dart';
export 'src/ui/live_state.dart';
export 'src/ui/sign_in_screen.dart';
export 'src/widgets/widgets.dart';
