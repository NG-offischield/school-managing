/// Shared infrastructure of the School Managing mobile apps (teacher today;
/// parent, guardian and staff later): API client and errors, session and
/// secure token storage, activation, real time, theme and components.
/// No business rule: the Django API is the source of truth.
library;

export 'src/api/api_client.dart';
export 'src/api/api_error.dart';
export 'src/auth/auth_service.dart';
export 'src/auth/identity.dart';
export 'src/auth/token_store.dart';
export 'src/messages.dart';
export 'src/realtime/realtime_client.dart';
export 'src/theme/app_theme.dart';
export 'src/widgets/widgets.dart';
