import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:provider/provider.dart';
import 'package:school_core/school_core.dart';

import 'l10n/teacher_en.dart';

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
    this.now,
  });

  final AuthService auth;
  final TeacherRepository repository;

  /// Where a PDF school plan goes to be shown by the phone's viewer (school_core).
  final PlanFiles planFiles;

  /// Live connection (existing ws/v1/realtime/); null = refresh by hand (tests).
  final RealtimeClient Function()? realtime;

  /// Clock of the date-based screens (planning, dashboard); null = DateTime.now.
  /// Tests pin it so that "today" and "this week" do not depend on the day they run.
  final DateTime Function()? now;

  @override
  Widget build(BuildContext context) {
    L10n.register(teacherEnglish); // this app's own English texts (shared ones: school_core)
    return MultiProvider(
      providers: [
        ChangeNotifierProvider<AuthService>.value(value: auth),
        Provider<TeacherRepository>.value(value: repository),
        Provider<CommunicationRepository>.value(value: repository),
        Provider<PlanFiles>.value(value: planFiles),
      ],
      child: MaterialApp(
        title: tr('School Managing — Enseignant'),
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
        home: AuthGate(realtime: realtime, now: now),
      ),
    );
  }
}

class AuthGate extends StatelessWidget {
  const AuthGate({super.key, this.realtime, this.now});

  final RealtimeClient Function()? realtime;
  final DateTime Function()? now;

  @override
  Widget build(BuildContext context) {
    final auth = context.watch<AuthService>();
    return switch (auth.status) {
      AuthStatus.restoring => const SplashScreen(),
      AuthStatus.signedOut || AuthStatus.pending => SignInScreen(
        // no pending accounts here
        subtitle: tr('Espace enseignant'),
        roleLabel: 'enseignant',
        alternative: SignInAlternative.activation(),
      ),
      AuthStatus.signedIn => HomeShell(key: ValueKey(auth.identity?.userId), realtime: realtime, now: now),
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
            SoftwareBrand(light: true, size: 30, subtitle: tr('Espace enseignant')),
            SizedBox(height: 28),
            CircularProgressIndicator(color: Colors.white, semanticsLabel: tr('Ouverture de la session')),
          ],
        ),
      ),
    );
  }
}
