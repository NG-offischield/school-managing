import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:provider/provider.dart';
import 'package:school_core/school_core.dart';

import 'data/guardian_repository.dart';
import 'presentation/home_shell.dart';

/// Root: the session decides the screen (splash -> sign in / activation -> home).
class GuardianApp extends StatelessWidget {
  const GuardianApp({super.key, required this.auth, required this.repository, this.realtime});

  final AuthService auth;
  final GuardianRepository repository;

  /// Live connection (existing ws/v1/realtime/); null = refresh by hand (tests).
  final RealtimeClient Function()? realtime;

  @override
  Widget build(BuildContext context) {
    return MultiProvider(
      providers: [
        ChangeNotifierProvider<AuthService>.value(value: auth),
        Provider<GuardianRepository>.value(value: repository),
        Provider<CommunicationRepository>.value(value: repository),
        Provider<GateRepository>.value(value: repository.gate),
      ],
      child: MaterialApp(
        title: 'School Managing — Gardien',
        debugShowCheckedModeBanner: false,
        theme: buildAppTheme(),
        locale: const Locale('fr', 'FR'),
        supportedLocales: const [Locale('fr', 'FR')],
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
      AuthStatus.restoring => const Scaffold(
        backgroundColor: Tokens.navy,
        body: Center(child: SoftwareBrand(light: true, size: 30, subtitle: 'Espace gardien')),
      ),
      AuthStatus.signedOut || AuthStatus.pending => SignInScreen(
        subtitle: 'Espace gardien',
        roleLabel: 'gardien',
        alternative: SignInAlternative.activation(),
      ),
      AuthStatus.signedIn => HomeShell(key: ValueKey(auth.identity?.userId), realtime: realtime),
    };
  }
}
