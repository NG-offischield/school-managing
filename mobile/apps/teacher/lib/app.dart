import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:provider/provider.dart';
import 'package:school_core/school_core.dart';

import 'data/teacher_repository.dart';
import 'presentation/home/home_shell.dart';

/// Root: session state decides the screen (splash -> login -> home).
class TeacherApp extends StatelessWidget {
  const TeacherApp({
    super.key,
    required this.auth,
    required this.repository,
    this.planFiles = const DevicePlanFiles(),
    this.realtime,
  });

  final AuthService auth;
  final TeacherRepository repository;

  /// Where a PDF school plan goes to be shown by the phone's viewer (school_core).
  final PlanFiles planFiles;

  /// Live connection (existing ws/v1/realtime/); null = refresh by hand (tests).
  final RealtimeClient Function()? realtime;

  @override
  Widget build(BuildContext context) {
    return MultiProvider(
      providers: [
        ChangeNotifierProvider<AuthService>.value(value: auth),
        Provider<TeacherRepository>.value(value: repository),
        Provider<CommunicationRepository>.value(value: repository),
        Provider<PlanFiles>.value(value: planFiles),
      ],
      child: MaterialApp(
        title: 'School Managing — Enseignant',
        debugShowCheckedModeBanner: false,
        theme: buildAppTheme(),
        darkTheme: buildAppTheme(brightness: Brightness.dark),
        themeMode: themeModeOf(context),
        builder: themedScreens,
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
      AuthStatus.restoring => const SplashScreen(),
      AuthStatus.signedOut || AuthStatus.pending => SignInScreen(
        // no pending accounts here
        subtitle: 'Espace enseignant',
        roleLabel: 'enseignant',
        alternative: SignInAlternative.activation(),
      ),
      AuthStatus.signedIn => HomeShell(key: ValueKey(auth.identity?.userId), realtime: realtime),
    };
  }
}

class SplashScreen extends StatelessWidget {
  const SplashScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Tokens.navy,
      body: Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            SoftwareBrand(light: true, size: 30, subtitle: 'Espace enseignant'),
            SizedBox(height: 28),
            CircularProgressIndicator(color: Colors.white, semanticsLabel: 'Ouverture de la session'),
          ],
        ),
      ),
    );
  }
}
