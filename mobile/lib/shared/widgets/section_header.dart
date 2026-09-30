import 'package:flutter/material.dart';

import '../../core/config/app_theme.dart';

class SectionHeader extends StatelessWidget {
  const SectionHeader({required this.title, this.action, super.key});
  final String title;
  final Widget? action;

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisAlignment: MainAxisAlignment.spaceBetween,
      children: [
        Text(title, style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700, color: AppColors.textPrimary)),
        if (action != null) action!,
      ],
    );
  }
}
