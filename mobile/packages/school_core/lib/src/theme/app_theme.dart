/// Single theme of the mobile apps — same tokens as the desktop
/// (desktop/school_admin/ui/theme.py): navy + blue, strong contrasts
/// (WCAG 2.1: 4.5:1 for text), large touch targets (48 dp minimum).
library;

import 'package:flutter/material.dart';

abstract final class Tokens {
  static const background = Color(0xFFF3F5F8);
  static const surface = Color(0xFFFFFFFF);
  static const primary = Color(0xFF1D4ED8);
  static const primaryDark = Color(0xFF1E3A8A);
  static const primarySoft = Color(0xFFDBEAFE);
  static const navy = Color(0xFF0F2747);
  static const text = Color(0xFF111827);
  static const textSecondary = Color(0xFF4B5563);
  static const border = Color(0xFFD5DCE5);
  static const fieldBorder = Color(0xFF7B8794);
  static const error = Color(0xFFB91C1C);
  static const errorBg = Color(0xFFFEF2F2);
  static const success = Color(0xFF166534);
  static const successBg = Color(0xFFF0FDF4);
  static const warning = Color(0xFF92400E);
  static const warningBg = Color(0xFFFFFBEB);
  static const info = Color(0xFF1E40AF);
  static const infoBg = Color(0xFFEFF6FF);
}

ThemeData buildAppTheme() {
  final scheme = ColorScheme.fromSeed(
    seedColor: Tokens.primary,
    primary: Tokens.primary,
    onPrimary: Colors.white,
    secondary: Tokens.navy,
    error: Tokens.error,
    surface: Tokens.surface,
    onSurface: Tokens.text,
  );
  const radius = BorderRadius.all(Radius.circular(10));
  return ThemeData(
    useMaterial3: true,
    colorScheme: scheme,
    scaffoldBackgroundColor: Tokens.background,
    appBarTheme: const AppBarTheme(
      backgroundColor: Tokens.navy,
      foregroundColor: Colors.white,
      centerTitle: false,
      elevation: 0,
    ),
    cardTheme: const CardThemeData(
      color: Tokens.surface,
      elevation: 0,
      margin: EdgeInsets.zero,
      shape: RoundedRectangleBorder(
        borderRadius: radius,
        side: BorderSide(color: Tokens.border),
      ),
    ),
    inputDecorationTheme: const InputDecorationTheme(
      filled: true,
      fillColor: Tokens.surface,
      border: OutlineInputBorder(
        borderRadius: radius,
        borderSide: BorderSide(color: Tokens.fieldBorder),
      ),
      enabledBorder: OutlineInputBorder(
        borderRadius: radius,
        borderSide: BorderSide(color: Tokens.fieldBorder),
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: radius,
        borderSide: BorderSide(color: Tokens.primary, width: 2),
      ),
      contentPadding: EdgeInsets.symmetric(horizontal: 14, vertical: 14),
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
        side: const BorderSide(color: Tokens.fieldBorder),
        foregroundColor: Tokens.text,
      ),
    ),
    navigationBarTheme: NavigationBarThemeData(
      backgroundColor: Tokens.surface,
      indicatorColor: Tokens.primarySoft,
      labelTextStyle: WidgetStateProperty.all(const TextStyle(fontSize: 12, fontWeight: FontWeight.w600)),
    ),
    listTileTheme: const ListTileThemeData(minVerticalPadding: 10),
  );
}
