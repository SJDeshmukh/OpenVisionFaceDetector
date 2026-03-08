import gradio as gr
from inference import process_webcam_frame

APP_TITLE = "Standalone Live 3D Face Mesh"

with gr.Blocks(title=APP_TITLE) as demo:
    gr.Markdown(f"# {APP_TITLE}")
    gr.Markdown("Real-time 3D face mesh overlay using 3DDFA-V3.")

    with gr.Row():
        with gr.Column():
            webcam_input = gr.Image(sources=["webcam"], streaming=True, label="Webcam Feed")
        with gr.Column():
            webcam_output = gr.Image(label="Real-Time Overlay")

    webcam_input.stream(
        fn=process_webcam_frame,
        inputs=webcam_input,
        outputs=webcam_output
    )

if __name__ == "__main__":
    demo.queue()
    demo.launch(share=False)
