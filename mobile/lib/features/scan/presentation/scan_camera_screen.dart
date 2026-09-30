import 'dart:io';

import 'package:camera/camera.dart';
import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:path_provider/path_provider.dart';

import '../../../core/config/app_theme.dart';

class ScanCameraScreen extends StatefulWidget {
  const ScanCameraScreen({super.key});

  @override
  State<ScanCameraScreen> createState() => _ScanCameraScreenState();
}

class _ScanCameraScreenState extends State<ScanCameraScreen> {
  CameraController? _controller;
  List<CameraDescription> _cameras = [];
  bool _initialized = false;
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    _setup();
  }

  Future<void> _setup() async {
    _cameras = await availableCameras();
    if (_cameras.isEmpty) return;

    final rear = _cameras.firstWhere(
      (c) => c.lensDirection == CameraLensDirection.back,
      orElse: () => _cameras.first,
    );
    _controller = CameraController(rear, ResolutionPreset.high, enableAudio: false);
    await _controller!.initialize();
    if (mounted) setState(() => _initialized = true);
  }

  @override
  void dispose() {
    _controller?.dispose();
    super.dispose();
  }

  Future<void> _capture() async {
    if (_controller == null || _busy) return;
    setState(() => _busy = true);
    try {
      final photo = await _controller!.takePicture();
      final dir = await getApplicationDocumentsDirectory();
      final dest = '${dir.path}/scan_${DateTime.now().millisecondsSinceEpoch}.jpg';
      await File(photo.path).copy(dest);
      if (mounted) {
        context.go('/scan/process', extra: dest);
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    if (!_initialized) {
      return const Scaffold(body: Center(child: CircularProgressIndicator()));
    }

    return Scaffold(
      backgroundColor: Colors.black,
      body: Stack(
        children: [
          CameraPreview(_controller!),
          // Overlay cadre
          Center(
            child: Container(
              margin: const EdgeInsets.symmetric(horizontal: 30),
              decoration: BoxDecoration(
                border: Border.all(color: AppColors.brand, width: 3),
                borderRadius: BorderRadius.circular(12),
              ),
              child: const AspectRatio(
                aspectRatio: 3 / 4,
                child: SizedBox.expand(),
              ),
            ),
          ),
          // Bouton capture
          Positioned(
            bottom: 40,
            left: 0, right: 0,
            child: Center(
              child: GestureDetector(
                onTap: _capture,
                child: Container(
                  width: 72, height: 72,
                  decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    color: Colors.white,
                    border: Border.all(color: AppColors.brand, width: 4),
                  ),
                  child: _busy
                      ? const Padding(
                          padding: EdgeInsets.all(20),
                          child: CircularProgressIndicator(strokeWidth: 3),
                        )
                      : null,
                ),
              ),
            ),
          ),
          // Close
          Positioned(
            top: MediaQuery.of(context).padding.top + 12,
            left: 12,
            child: IconButton(
              onPressed: () => context.pop(),
              icon: const Icon(Icons.close, color: Colors.white, size: 28),
            ),
          ),
        ],
      ),
    );
  }
}
