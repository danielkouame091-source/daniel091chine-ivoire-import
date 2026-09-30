import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/config/app_theme.dart';
import '../../../core/network/api_client.dart';
import '../../../shared/utils/format.dart';
import '../../../../features/invoices/data/models/invoice.dart';

class ScanProcessScreen extends ConsumerStatefulWidget {
  const ScanProcessScreen({required this.imagePath, super.key});
  final String imagePath;

  @override
  ConsumerState<ScanProcessScreen> createState() => _ScanProcessScreenState();
}

class _ScanProcessScreenState extends ConsumerState<ScanProcessScreen> {
  bool _uploading = true;
  String? _error;
  Map<String, dynamic>? _extraction;

  @override
  void initState() {
    super.initState();
    _upload();
  }

  Future<void> _upload() async {
    try {
      final dio = ApiClient.dio;
      final file = File(widget.imagePath);

      final formData = FormData.fromMap({
        'file': await MultipartFile.fromFile(file.path),
        'type_document': 'facture_fournisseur',
      });

      final response = await dio.post(
        '/api/v1/ged/documents/upload',
        data: formData,
      );

      final docId = response.data['document']['id'];

      // Attendre la fin de l'OCR (polling)
      await Future.delayed(const Duration(seconds: 3));
      final ocr = await dio.get('/api/v1/ged/documents/$docId/ocr');

      if (mounted) {
        setState(() {
          _uploading = false;
          _extraction = ocr.data;
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _uploading = false;
          _error = e.toString();
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Analyse OCR')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          // Image capturée
          ClipRRect(
            borderRadius: BorderRadius.circular(12),
            child: Image.file(File(widget.imagePath), height: 220, fit: BoxFit.cover),
          ),
          const SizedBox(height: 24),

          if (_uploading)
            const Center(
              child: Column(
                children: [
                  CircularProgressIndicator(),
                  SizedBox(height: 12),
                  Text('Analyse en cours…'),
                ],
              ),
            )
          else if (_error != null)
            Text('Erreur : $_error', style: const TextStyle(color: AppColors.danger))
          else if (_extraction != null)
            _ExtractionForm(data: _extraction!),
        ],
      ),
    );
  }
}

class _ExtractionForm extends StatelessWidget {
  const _ExtractionForm({required this.data});
  final Map<String, dynamic> data;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text('Données extraites',
            style: TextStyle(fontSize: 18, fontWeight: FontWeight.w700)),
        const SizedBox(height: 4),
        Text(
          'Score de confiance : ${((data['score_global'] ?? 0) * 100).toStringAsFixed(0)}%',
          style: const TextStyle(color: AppColors.textMuted, fontSize: 13),
        ),
        const SizedBox(height: 16),
        _Field(label: 'N° facture', value: data['num_facture'] ?? '—'),
        _Field(label: 'Nom fournisseur', value: data['nom_fournisseur'] ?? '—'),
        _Field(label: 'Date', value: data['date_facture'] ?? '—'),
        _Field(label: 'Montant HT', value: data['montant_ht'] != null ? Format.xof(data['montant_ht'] as int) : '—'),
        _Field(label: 'TVA', value: data['montant_tva'] != null ? Format.xof(data['montant_tva'] as int) : '—'),
        _Field(label: 'Total TTC', value: data['montant_ttc'] != null ? Format.xof(data['montant_ttc'] as int) : '—'),
        const SizedBox(height: 24),
        ElevatedButton.icon(
          onPressed: () => context.go('/invoices'),
          icon: const Icon(Icons.check),
          label: const Text('Créer la facture fournisseur'),
        ),
      ],
    );
  }
}

class _Field extends StatelessWidget {
  const _Field({required this.label, required this.value});
  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Row(
        children: [
          SizedBox(width: 130, child: Text(label, style: const TextStyle(color: AppColors.textMuted))),
          Expanded(child: Text(value, style: const TextStyle(fontWeight: FontWeight.w500))),
        ],
      ),
    );
  }
}
