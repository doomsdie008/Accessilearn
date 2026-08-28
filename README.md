# AccessiLearn

### AI-Powered Accessible Learning Platform

AccessiLearn is an AI-powered learning platform designed to make educational content easier to access and understand. It transforms traditional learning materials such as textbooks, PDFs, images, diagrams, and video content into accessible, narrated learning experiences.

The platform uses Large Language Models (LLMs), image understanding, and Text-to-Speech technology to turn complex educational content into easy-to-follow audio lessons and transcripts.

---

## Features

### 📚 PDF & Textbook Processing
- Upload educational PDFs and extract their text content.
- Convert long textbook sections into simplified learning material.
- Generate structured, podcast-style explanations from educational content.

### 🖼️ Image & Diagram Understanding
- Process diagrams, figures, and educational images.
- Generate AI-powered descriptions of visual content.
- Convert visual information into explanations that can be understood through audio.

### 🎙️ AI Text-to-Speech
- Convert generated learning scripts into spoken audio.
- Generate downloadable MP3 lessons.
- Provide transcripts alongside generated audio.

### 🎥 Video Content Assistance
- Process descriptions of scenes from educational videos.
- Convert visual scenes into meaningful explanations.
- Combine video context with narration to create accessible learning content.

### ♿ Accessibility Features
- Keyboard-friendly navigation.
- High-contrast interface.
- Adjustable text size.
- Visible focus indicators.
- Voice narration using the Web Speech API.
- Audio-based navigation and content consumption.

---

## How It Works

```text
Educational Content
       │
       ▼
┌─────────────────────┐
│ PDF / Text / Image  │
│ / Video Content     │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│ Content Processing  │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│ LLM / Vision Model  │
│ Content Generation  │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│ Learning Script     │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│ Text-to-Speech      │
└──────────┬──────────┘
           │
           ▼
      🎧 Audio Lesson
       + Transcript
