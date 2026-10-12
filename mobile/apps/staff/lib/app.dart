import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:provider/provider.dart';
import 'package:school_core/school_core.dart';

import 'l10n/staff_en.dart';

import 'data/staff_repository.dart';
import 'presentation/home_shell.dart';

/// Root: the session decides the screen (splash -> sign in / activation -> home).
class StaffApp extends StatelessWidget {
  const StaffApp({super.key, required this.auth, required this.repository, this.realtime});

  final AuthService auth;
  final StaffRepository repository;

  /// Live connection (existing ws/v1/realtime/); null = refresh by hand (tests).
  final RealtimeClient Function()? realtime;

  @override
  Widget build(BuildContext context) {
    L10n.register(staffEnglish); // this app's own English texts (shared ones: school_core)
    return MultiProvider(
      providers: [
        ChangeNotifierProvider<AuthService>.value(value: auth),
        Provider<StaffRepository>.value(value: repository),
        Provider<CommunicationRepository>.value(value: repository),
        Provider<GateRepository>.value(value: repository.gate),
      ],
      child: MaterialApp(
        title: tr('School Managing — Personnel'),
        debugShowCheckedModeBanner: false,
        theme: buildAppTheme(),
        darkTheme: buildAppTheme(brightness: Brightness.dark),
        themeMode: themeModeOf(context),
        builder: themedScreens,
        locale: languageOf(context).locale,
        supportedLocales: supportedAppLocales,
        localizationsDelegates: const [
          GlobalMaterialLocalizations.delegate,
          GlobalWidgetsLocalizations.delegate,
          GlobalCupertinoLocalizations.delegate,
        ],
        home: AuthGate(realtime: realtime),
      ),
    );
  }
}

class AuthGate extends StatelessWidget {
  const AuthGate({super.key, this.realtime});

  final RealtimeClient Function()? realtime;

  @override
  Widget build(BuildContext context) {
    final auth = context.watch<AuthService>();
    return switch (auth.status) {
      AuthStatus.restoring => Scaffold(
        backgroundColor: Tokens.navy,
        body: Center(child: SoftwareBrand(light: true, size: 30, subtitle: tr('Espace personnel'))),
      ),
      AuthStatus.signedOut || AuthStatus.pending => SignInScreen(
        subtitle: tr('Espace personnel'),
        roleLabel: 'personnel',
        alternative: SignInAlternative.activation(),
      ),
      AuthStatus.signedIn => HomeShell(key: ValueKey(auth.identity?.userId), realtime: realtime),
    };
  }
}
