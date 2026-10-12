/// Theme of the mobile apps — same tokens as the desktop
/// (desktop/school_admin/ui/theme.py): navy + blue, strong contrasts
/// (WCAG 2.1: 4.5:1 for text, 3:1 for icons and borders), large touch targets
/// (48 dp minimum). Light and dark palettes; the user picks Système / Clair /
/// Sombre in « Mon compte » ([ThemeController], kept in shared_preferences).
library;

import 'package:flutter/material.dart';
import 'package:flutter/scheduler.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// One palette (light or dark): every colour the screens use.
class Palette {
  const Palette({
    required this.background,
    required this.surface,
    required this.primary,
    required this.onPrimary,
    required this.primaryDark,
    required this.primarySoft,
    required this.navy,
    required this.text,
    required this.textSecondary,
    required this.border,
    required this.fieldBorder,
    required this.error,
    required this.errorBg,
    required this.success,
    required this.successBg,
    required this.warning,
    required this.warningBg,
    required this.info,
    required this.infoBg,
    required this.neutralBg,
  });

  final Color background;
  final Color surface;
  final Color primary;
  final Color onPrimary;
  final Color primaryDark;
  final Color primarySoft;
  final Color navy;
  final Color text;
  final Color textSecondary;
  final Color border;
  final Color fieldBorder;
  final Color error;
  final Color errorBg;
  final Color success;
  final Color successBg;
  final Color warning;
  final Color warningBg;
  final Color info;
  final Color infoBg;
  final Color neutralBg;

  static const light = Palette(
    background: Color(0xFFF3F5F8),
    surface: Color(0xFFFFFFFF),
    primary: Color(0xFF1D4ED8),
    onPrimary: Color(0xFFFFFFFF),
    primaryDark: Color(0xFF1E3A8A),
    primarySoft: Color(0xFFDBEAFE),
    navy: Color(0xFF0F2747),
    text: Color(0xFF111827),
    textSecondary: Color(0xFF4B5563),
    border: Color(0xFFD5DCE5),
    fieldBorder: Color(0xFF7B8794),
    error: Color(0xFFB91C1C),
    errorBg: Color(0xFFFEF2F2),
    success: Color(0xFF166534),
    successBg: Color(0xFFF0FDF4),
    warning: Color(0xFF92400E),
    warningBg: Color(0xFFFFFBEB),
    info: Color(0xFF1E40AF),
    infoBg: Color(0xFFEFF6FF),
    neutralBg: Color(0xFFEEF1F5),
  );

  /// Dark: light text on slate surfaces. The blue is lighter (readable as
  /// text / icon on a dark surface) and carries DARK text when filled. The
  /// navy bars stay navy (white text on them in both themes).
  static const dark = Palette(
    background: Color(0xFF111827),
    surface: Color(0xFF1F2937),
    primary: Color(0xFF60A5FA),
    onPrimary: Color(0xFF0B1220),
    primaryDark: Color(0xFF93C5FD),
    primarySoft: Color(0xFF1E3A5F),
    navy: Color(0xFF0B1A33),
    text: Color(0xFFE5E7EB),
    textSecondary: Color(0xFFAAB4C3),
    border: Color(0xFF334155),
    fieldBorder: Color(0xFF6B7A90),
    error: Color(0xFFFCA5A5),
    errorBg: Color(0xFF3B1418),
    success: Color(0xFF86EFAC),
    successBg: Color(0xFF12301F),
    warning: Color(0xFFFCD34D),
    warningBg: Color(0xFF3A2A0B),
    info: Color(0xFF93C5FD),
    infoBg: Color(0xFF172B4A),
    neutralBg: Color(0xFF273244),
  );
}

/// The ACTIVE palette's colours. Screens read them when they build; the
/// palette follows the effective brightness of the app ([ThemedTokens]).
abstract final class Tokens {
  static Palette _palette = Palette.light;

  static Palette get palette => _palette;
  static bool get isDark => identical(_palette, Palette.dark);

  /// Tests / [ThemedTokens] only.
  static void use(Brightness brightness) => _palette = brightness == Brightness.dark ? Palette.dark : Palette.light;

  static Color get background => _palette.background;
  static Color get surface => _palette.surface;
  static Color get primary => _palette.primary;
  static Color get onPrimary => _palette.onPrimary;
  static Color get primaryDark => _palette.primaryDark;
  static Color get primarySoft => _palette.primarySoft;
  static Color get navy => _palette.navy;
  static Color get text => _palette.text;
  static Color get textSecondary => _palette.textSecondary;
  static Color get border => _palette.border;
  static Color get fieldBorder => _palette.fieldBorder;
  static Color get error => _palette.error;
  static Color get errorBg => _palette.errorBg;
  static Color get success => _palette.success;
  static Color get successBg => _palette.successBg;
  static Color get warning => _palette.warning;
  static Color get warningBg => _palette.warningBg;
  static Color get info => _palette.info;
  static Color get infoBg => _palette.infoBg;
  static Color get neutralBg => _palette.neutralBg;
}

ThemeData buildAppTheme({Brightness brightness = Brightness.light}) {
  final p = brightness == Brightness.dark ? Palette.dark : Palette.light;
  final scheme = ColorScheme.fromSeed(
    seedColor: p.primary,
    brightness: brightness,
    primary: p.primary,
    onPrimary: p.onPrimary,
    secondary: p.navy,
    error: p.error,
    surface: p.surface,
    onSurface: p.text,
    onSurfaceVariant: p.textSecondary,
    outline: p.fieldBorder,
    outlineVariant: p.border,
  );
  const radius = BorderRadius.all(Radius.circular(10));
  return ThemeData(
    useMaterial3: true,
    brightness: brightness,
    colorScheme: scheme,
    scaffoldBackgroundColor: p.background,
    appBarTheme: AppBarTheme(backgroundColor: p.navy, foregroundColor: Colors.white, centerTitle: false, elevation: 0),
    cardTheme: CardThemeData(
      color: p.surface,
      elevation: 0,
      margin: EdgeInsets.zero,
      shape: RoundedRectangleBorder(
        borderRadius: radius,
        side: BorderSide(color: p.border),
      ),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: p.surface,
      border: OutlineInputBorder(
        borderRadius: radius,
        borderSide: BorderSide(color: p.fieldBorder),
      ),
      enabledBorder: OutlineInputBorder(
        borderRadius: radius,
        borderSide: BorderSide(color: p.fieldBorder),
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: radius,
        borderSide: BorderSide(color: p.primary, width: 2),
      ),
      contentPadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 14),
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        minimumSize: const Size.fromHeight(52),
        shape: const RoundedRectangleBorder(borderRadius: radius),
        textStyle: const TextStyle(fontSize: 16, fontWeight: FontWeight.w600),
      ),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        minimumSize: const Size.fromHeight(48),
        shape: const RoundedRectangleBorder(borderRadius: radius),
        side: BorderSide(color: p.fieldBorder),
        foregroundColor: p.text,
      ),
    ),
    navigationBarTheme: NavigationBarThemeData(
      backgroundColor: p.surface,
      indicatorColor: p.primarySoft,
      labelTextStyle: WidgetStateProperty.all(const TextStyle(fontSize: 12, fontWeight: FontWeight.w600)),
    ),
    listTileTheme: const ListTileThemeData(minVerticalPadding: 10),
  );
}

/// Système / Clair / Sombre.
const themeModeLabels = {ThemeMode.system: 'Système', ThemeMode.light: 'Clair', ThemeMode.dark: 'Sombre'};

/// The user's choice, kept on the phone (shared_preferences: a display
/// preference, nothing secret). Default: follow the system.
class ThemeController extends ChangeNotifier {
  ThemeController({ThemeMode initial = ThemeMode.system}) : _mode = initial;

  static const key = 'school_managing.theme_mode';

  ThemeMode _mode;
  ThemeMode get mode => _mode;

  /// The saved choice (system when none / unknown).
  static Future<ThemeController> load() async {
    final prefs = await SharedPreferences.getInstance();
    final saved = ThemeMode.values.where((m) => m.name == prefs.getString(key)).firstOrNull;
    return ThemeController(initial: saved ?? ThemeMode.system);
  }

  Future<void> set(ThemeMode mode) async {
    if (mode == _mode) return;
    _mode = mode;
    notifyListeners();
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(key, mode.name);
  }
}

/// The mode for an app's MaterialApp: the user's choice ([ThemeController]
/// provided above the app by main()), light when there is none (widget tests).
ThemeMode themeModeOf(BuildContext context) => context.watch<ThemeController?>()?.mode ?? ThemeMode.light;

/// MaterialApp.builder of every app: [ThemedTokens] around the screens.
Widget themedScreens(BuildContext context, Widget? child) => ThemedTokens(child: child ?? const SizedBox.shrink());

/// Below MaterialApp (its `builder`): keeps [Tokens] on the EFFECTIVE
/// brightness (choice, or the phone's setting in « Système ») and, when it
/// changes, rebuilds every screen so colours read from [Tokens] follow —
/// without losing the navigation or what was typed.
class ThemedTokens extends StatefulWidget {
  const ThemedTokens({super.key, required this.child});

  final Widget child;

  @override
  State<ThemedTokens> createState() => _ThemedTokensState();
}

class _ThemedTokensState extends State<ThemedTokens> {
  Brightness? _applied;

  @override
  Widget build(BuildContext context) {
    final brightness = Theme.of(context).brightness;
    if (_applied != brightness) {
      final first = _applied == null;
      _applied = brightness;
      Tokens.use(brightness);
      if (!first) {
        SchedulerBinding.instance.addPostFrameCallback((_) {
          if (!mounted) return;
          void rebuild(Element element) {
            element.markNeedsBuild();
            element.visitChildren(rebuild);
          }

          (context as Element).visitChildren(rebuild);
        });
      }
    }
    return widget.child;
  }
}
