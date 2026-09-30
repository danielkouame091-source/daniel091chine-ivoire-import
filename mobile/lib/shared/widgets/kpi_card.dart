import 'package:flutter/material.dart';

import '../../core/config/app_theme.dart';

class KpiCard extends StatelessWidget {
  const KpiCard({
    required this.label,
    required this.value,
    required this.icon,
    required this.color,
    this.variationPct,
    this.badge,
    this.badgeColor,
    super.key,
  });

  final String label;
  final String value;
  final IconData icon;
  final Color color;
  final double? variationPct;
  final String? badge;
  final Color? badgeColor;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AppColors.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Container(
                padding: const EdgeInsets.all(6),
                decoration: BoxDecoration(
                  color: color.withOpacity(0.12),
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Icon(icon, color: color, size: 18),
              ),
              if (variationPct != null)
                Row(
                  children: [
                    Icon(
                      variationPct! >= 0 ? Icons.arrow_upward : Icons.arrow_downward,
                      size: 12,
                      color: variationPct! >= 0 ? AppColors.success : AppColors.danger,
                    ),
                    Text(
                      '${variationPct!.abs().toStringAsFixed(1)}%',
                      style: TextStyle(
                        color: variationPct! >= 0 ? AppColors.success : AppColors.danger,
                        fontSize: 11,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                  ],
                ),
              if (badge != null)
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                  decoration: BoxDecoration(
                    color: (badgeColor ?? AppColors.danger).withOpacity(0.1),
                    borderRadius: BorderRadius.circular(20),
                  ),
                  child: Text(
                    badge!,
                    style: TextStyle(
                      color: badgeColor ?? AppColors.danger,
                      fontSize: 10,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ),
            ],
          ),
          const SizedBox(height: 8),
          Text(label, style: const TextStyle(color: AppColors.textMuted, fontSize: 11, fontWeight: FontWeight.w500)),
          const SizedBox(height: 2),
          Text(value, style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w700), overflow: TextOverflow.ellipsis),
        ],
      ),
    );
  }
}
