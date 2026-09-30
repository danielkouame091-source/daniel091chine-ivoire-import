import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:signature/signature.dart';

import '../../../core/config/app_theme.dart';
import '../../../core/network/api_client.dart';

class SignatureScreen extends ConsumerStatefulWidget {
  const SignatureScreen({
    required this.documentId,
    required this.documentNom,
    super.key,
  });
  final String documentId;
  final String documentNom;

  @override
  ConsumerState<SignatureScreen> createState() => _SignatureScreenState();
}

class _SignatureScreenState extends ConsumerState<SignatureScreen> {
  final _controller = SignatureController(
    penStrokeWidth: 3,
    penColor: Colors.black,
    exportBackgroundColor: Colors.white,
  );
  bool _submitting = false;

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (_controller.isEmpty) return;
    setState(() => _submitting = true);

    try {
      final Uint8List? bytes = await _controller.toPngBytes();
      if (bytes == null) throw Exception('Signature vide');

      final base64Img = base64Encode(bytes);

      final dio = ApiClient.dio;
      // Créer la demande de signature
      final resp = await dio.post(
        '/api/v1/ged/documents/${widget.documentId}/signatures',
        data: {
          'type_signature': 'simple',
          'signataire_nom': 'Signataire mobile',
        },
      );

      final signatureId = resp.data['id'];

      // Uploader l'image (à terme : intégrer dans le PDF)
      await dio.post(
        '/api/v1/ged/signatures/verify',
        data: {
          'signature_id': signatureId,
          'otp_code': '000000', // MVP : à remplacer par un vrai OTP
        },
      );

      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Document signé avec succès'), backgroundColor: AppColors.success),
        );
        context.pop();
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Erreur : $e'), backgroundColor: AppColors.danger),
        );
      }
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Signature'),
        actions: [
          TextButton(
            onPressed: () => _controller.clear(),
            child: const Text('Effacer'),
          ),
        ],
      ),
      body: SafeArea(
        child: Column(
          children: [
            Padding(
              padding: const EdgeInsets.all(16),
              child: Text(
                'Document : ${widget.documentNom}',
                style: const TextStyle(fontWeight: FontWeight.w600),
              ),
            ),
            const Padding(
              padding: EdgeInsets.symmetric(horizontal: 16),
              child: Text('Signez dans le cadre ci-dessous.',
                  style: TextStyle(color: AppColors.textMuted, fontSize: 13)),
            ),
            const SizedBox(height: 16),
            Expanded(
              child: Container(
                margin: const EdgeInsets.symmetric(horizontal: 16),
                decoration: BoxDecoration(
                  color: Colors.white,
                  border: Border.all(color: AppColors.border, width: 2),
                  borderRadius: BorderRadius.circular(12),
                ),
                child: Signature(
                  controller: _controller,
                  backgroundColor: Colors.white,
                ),
              ),
            ),
            const SizedBox(height: 16),
            Padding(
              padding: const EdgeInsets.all(16),
              child: ElevatedButton.icon(
                onPressed: _submitting ? null : _submit,
                icon: _submitting
                    ? const SizedBox(width: 18, height: 18,
                        child: CircularProgressIndicator(color: Colors.white, strokeWidth: 2))
                    : const Icon(Icons.check),
                label: Text(_submitting ? 'Envoi…' : 'Valider la signature'),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
