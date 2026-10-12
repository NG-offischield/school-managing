import 'dart:math';

import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:intl/date_symbol_data_local.dart';
import 'package:provider/provider.dart';
import 'package:school_core/school_core.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'account_test.dart' show FakeAccountServer, pumpAccountWith;

/// Système / Clair / Sombre: both palettes keep WCAG 2.1 contrasts, the
/// choice is applied at once (open screens included, nothing typed is lost)
/// and kept on the phone; shared screens render in both themes.

double _luminance(Color c) {
  double channel(double v) => v <= 0.03928 ? v / 12.92 : pow((v + 0.055) / 1.055, 2.4).toDouble();
  return 0.2126 * channel(c.r) + 0.7152 * channel(c.g) + 0.0722 * channel(c.b);
}

double contrast(Color a, Color b) {
  final la = _luminance(a), lb = _luminance(b);
  return (max(la, lb) + 0.05) / (min(la, lb) + 0.05);
}

void main() {
  setUpAll(() => initializeDateFormatting('fr_FR'));
  tearDown(() => Tokens.use(Brightness.light));

  for (final (name, p) in [('light', Palette.light), ('dark', Palette.dark)]) {
    test('$name palette meets WCAG 2.1', () {
      final pairs = <String, (Color, Color, double)>{
        'text/surface': (p.text, p.surface, 4.5),
        'text/background': (p.text, p.background, 4.5),
        'textSecondary/surface': (p.textSecondary, p.surface, 4.5),
        'textSecondary/background': (p.textSecondary, p.background, 4.5),
        'onPrimary/primary': (p.onPrimary, p.primary, 4.5),
        'primary/surface (links, icons)': (p.primary, p.surface, 4.5),
        'error/errorBg': (p.error, p.errorBg, 4.5),
        'success/successBg': (p.success, p.successBg, 4.5),
        'warning/warningBg': (p.warning, p.warningBg, 4.5),
        'info/infoBg': (p.info, p.infoBg, 4.5),
        'textSecondary/neutralBg': (p.textSecondary, p.neutralBg, 4.5),
        'text/primarySoft': (p.text, p.primarySoft, 4.5),
        'white/navy (app bar)': (Colors.white, p.navy, 4.5),
        'error/surface': (p.error, p.surface, 4.5),
        'fieldBorder/surface': (p.fieldBorder, p.surface, 3.0),
      };
      pairs.forEach((label, pair) {
        expect(contrast(pair.$1, pair.$2), greaterThanOrEqualTo(pair.$3), reason: '$name $label');
      });
    });
  }

  test('the choice is kept on the phone (system by default)', () async {
    SharedPreferences.setMockInitialValues({});
    expect((await ThemeController.load()).mode, ThemeMode.system);
    final controller = await ThemeController.load();
    await controller.set(ThemeMode.dark);
    expect((await ThemeController.load()).mode, ThemeMode.dark);
    SharedPreferences.setMockInitialValues({ThemeController.key: 'violet'});
    expect((await ThemeController.load()).mode, ThemeMode.system);
  });

  testWidgets('switching applies at once to the open screen, keeping what was typed', (tester) async {
    SharedPreferences.setMockInitialValues({});
    final controller = ThemeController(initial: ThemeMode.light);
    final typed = TextEditingController(text: 'Ma réponse');
    await tester.pumpWidget(
      ChangeNotifierProvider<ThemeController>.value(
        value: controller,
        child: Builder(
          builder: (context) => MaterialApp(
            theme: buildAppTheme(),
            darkTheme: buildAppTheme(brightness: Brightness.dark),
            themeMode: themeModeOf(context),
            builder: themedScreens,
            home: Scaffold(
              body: Column(
                children: [
                  const _Probe(),
                  TextField(controller: typed),
                  const MessageBanner('Attention', tone: Tone.warning),
                ],
              ),
            ),
          ),
        ),
      ),
    );
    Color labelColour() => tester.widget<Text>(find.byKey(const Key('label'))).style!.color!;
    expect(labelColour(), Palette.light.textSecondary);
    await controller.set(ThemeMode.dark);
    await tester.pumpAndSettle();
    expect(Tokens.isDark, isTrue);
    expect(labelColour(), Palette.dark.textSecondary);
    expect(Theme.of(tester.element(find.byType(TextField))).brightness, Brightness.dark);
    expect(find.text('Ma réponse'), findsOneWidget); // state kept
    await controller.set(ThemeMode.light);
    await tester.pumpAndSettle();
    expect(labelColour(), Palette.light.textSecondary);
  });

  testWidgets('« Système » follows the phone', (tester) async {
    tester.platformDispatcher.platformBrightnessTestValue = Brightness.dark;
    addTearDown(tester.platformDispatcher.clearPlatformBrightnessTestValue);
    await tester.pumpWidget(
      ChangeNotifierProvider<ThemeController>.value(
        value: ThemeController(),
        child: Builder(
          builder: (context) => MaterialApp(
            theme: buildAppTheme(),
            darkTheme: buildAppTheme(brightness: Brightness.dark),
            themeMode: themeModeOf(context),
            builder: themedScreens,
            home: const Scaffold(body: Text('x')),
          ),
        ),
      ),
    );
    expect(Tokens.isDark, isTrue);
    tester.platformDispatcher.platformBrightnessTestValue = Brightness.light;
    await tester.pumpAndSettle();
    expect(Tokens.isDark, isFalse);
  });

  for (final mode in [ThemeMode.light, ThemeMode.dark]) {
    testWidgets('« Mon compte » renders in ${mode.name} and offers the theme choice', (tester) async {
      SharedPreferences.setMockInitialValues({});
      final controller = ThemeController(initial: mode);
      await pumpAccountWith(tester, FakeAccountServer(), theme: controller);
      expect(tester.takeException(), isNull);
      expect(Tokens.isDark, mode == ThemeMode.dark);
      await tester.scrollUntilVisible(
        find.byKey(const Key('account.password')), // below the theme section: then fully visible
        200,
        scrollable: find.byType(Scrollable).first,
      );
      final other = mode == ThemeMode.dark ? ThemeMode.light : ThemeMode.dark;
      await tester.tap(find.byKey(Key('account.theme.${other.name}')));
      await tester.pumpAndSettle();
      expect(controller.mode, other);
      expect(Tokens.isDark, other == ThemeMode.dark);
      expect(tester.takeException(), isNull);
    });
  }

  testWidgets('without a ThemeController the app stays light and the choice is hidden', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        localizationsDelegates: const [GlobalMaterialLocalizations.delegate, GlobalWidgetsLocalizations.delegate],
        home: Builder(builder: (context) => Text('${themeModeOf(context)}')),
      ),
    );
    expect(find.text('ThemeMode.light'), findsOneWidget);
    await tester.pumpWidget(const MaterialApp(home: Scaffold(body: ThemeChoice())));
    expect(find.byKey(const Key('account.theme')), findsNothing);
  });
}

/// Like every screen: reads [Tokens] in its own build.
class _Probe extends StatelessWidget {
  const _Probe();

  @override
  Widget build(BuildContext context) => Text(
    'Libellé',
    key: const Key('label'),
    style: TextStyle(color: Tokens.textSecondary),
  );
}
