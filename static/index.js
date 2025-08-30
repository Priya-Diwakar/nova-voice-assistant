document.addEventListener("DOMContentLoaded", () => {
    let audioContext = null;
    let source = null;
    let processor = null;
    let isRecording = false;
    let socket = null;
    let heartbeatInterval = null;

    let audioQueue = [];
    let isPlaying = false;
    let currentAiMessageContentElement = null;
    let audioChunkIndex = 0;
    let lastAiMessage = ""; 
    let currentAudioSource = null; 

    const recordBtn = document.getElementById("recordBtn");
    const statusDisplay = document.getElementById("statusDisplay");
    const chatDisplay = document.getElementById("chatDisplay");
    const chatContainer = document.getElementById("chatContainer");
    const clearBtnContainer = document.getElementById("clearBtnContainer");
    const clearBtn = document.getElementById("clearBtn");

    // 🔑 API Key Management
    const saveKeysBtn = document.getElementById("saveKeysBtn");
    const saveMsg = document.getElementById("saveMsg");

    saveKeysBtn.addEventListener("click", () => {
        const keys = {
            murf: document.getElementById("murfKey").value,
            assembly: document.getElementById("assemblyKey").value,
            gemini: document.getElementById("geminiKey").value,
            news: document.getElementById("newsKey").value,
            weather: document.getElementById("weatherKey").value
        };
        localStorage.setItem("apiKeys", JSON.stringify(keys));
        saveMsg.classList.remove("hidden");
        setTimeout(() => saveMsg.classList.add("hidden"), 2000);
    });

    const getSavedKeys = () => {
        try {
            return JSON.parse(localStorage.getItem("apiKeys")) || {};
        } catch {
            return {};
        }
    };

    const stopCurrentPlayback = () => {
        if (currentAudioSource) {
            currentAudioSource.stop();
            currentAudioSource = null;
        }
        audioQueue = []; 
        isPlaying = false;
    };

    const playNextChunk = () => {
        if (!audioQueue.length || !audioContext || audioContext.state === "closed") {
            isPlaying = false;
            currentAudioSource = null;
            return;
        }
        isPlaying = true;
        const chunk = audioQueue.shift(); 
        audioContext.decodeAudioData(chunk,
            (buffer) => {
                const sourceNode = audioContext.createBufferSource();
                sourceNode.buffer = buffer;
                sourceNode.connect(audioContext.destination);
                sourceNode.start();
                currentAudioSource = sourceNode;
                sourceNode.onended = () => {
                    currentAudioSource = null;
                    playNextChunk();
                };
            },
            () => playNextChunk()
        );
    };

    let persona = "Friendly"; 
    document.getElementById("personaSelect").addEventListener("change", function () {
        persona = this.value;
    });

    const startRecording = async () => {
        if (!audioContext) {
            audioContext = new (window.AudioContext || window.webkitAudioContext)();
        }
        if (audioContext.state === 'suspended') {
            await audioContext.resume();
        }

        isRecording = true;
        updateUIForRecording(true);

        try {
            const wsProtocol = window.location.protocol === "https:" ? "wss:" : "ws:";
            
            // ✅ Load keys from localStorage
            const keys = getSavedKeys();
            const queryParams = new URLSearchParams({
                persona,
                murfKey: keys.murf || "",
                assemblyKey: keys.assembly || "",
                geminiKey: keys.gemini || "",
                newsKey: keys.news || "",
                weatherKey: keys.weather || ""
            });

            // ✅ WebSocket includes persona + all API keys
            socket = new WebSocket(`${wsProtocol}//${window.location.host}/ws?${queryParams.toString()}`);

            socket.onopen = async () => {
                heartbeatInterval = setInterval(() => {
                    if (socket?.readyState === WebSocket.OPEN) {
                        socket.send(JSON.stringify({ type: "ping" }));
                    }
                }, 25000);

                try {
                    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
                    source = audioContext.createMediaStreamSource(stream);
                    processor = audioContext.createScriptProcessor(4096, 1, 1);

                    processor.onaudioprocess = (event) => {
                        const inputData = event.inputBuffer.getChannelData(0);
                        const targetSampleRate = 16000;
                        const sourceSampleRate = audioContext.sampleRate;
                        const ratio = sourceSampleRate / targetSampleRate;
                        const newLength = Math.floor(inputData.length / ratio);
                        const downsampledData = new Float32Array(newLength);
                        for (let i = 0; i < newLength; i++) {
                            downsampledData[i] = inputData[Math.floor(i * ratio)];
                        }
                        const pcmData = new Int16Array(downsampledData.length);
                        for (let i = 0; i < pcmData.length; i++) {
                            const sample = Math.max(-1, Math.min(1, downsampledData[i]));
                            pcmData[i] = sample < 0 ? sample * 0x8000 : sample * 0x7FFF;
                        }
                        if (socket?.readyState === WebSocket.OPEN) {
                            socket.send(pcmData.buffer);
                        }
                    };

                    source.connect(processor);
                    processor.connect(audioContext.destination);
                    recordBtn.mediaStream = stream;
                } catch (micError) {
                    alert("Mic error: " + micError.message);
                    await stopRecording();
                }
            };

            socket.onmessage = async (event) => {
                try {
                    const data = JSON.parse(event.data);

                    switch (data.type) {
                        case "pong": break;
                        case "status":
                            statusDisplay.textContent = data.message;
                            break;
                        case "transcription":
                            if (data.end_of_turn && data.text) {
                                addToChatLog(data.text, 'user');
                                statusDisplay.textContent = "Nova is thinking...";
                                currentAiMessageContentElement = null;

                                if (data.text.toLowerCase().includes("weather")) {
                                    fetchSkill("weather");
                                } else if (data.text.toLowerCase().includes("news")) {
                                    fetchSkill("news");
                                }
                            }
                            break;
                        case "llm_chunk":
                            if (data.data) {
                                if (!currentAiMessageContentElement) {
                                    currentAiMessageContentElement = addToChatLog("", 'ai');
                                    lastAiMessage = "";
                                }
                                currentAiMessageContentElement.textContent += data.data;
                                lastAiMessage += data.data;
                                chatContainer.scrollTop = chatContainer.scrollHeight;
                            }
                            break;
                        case "audio":
                            if (data.data) {
                                const audioData = atob(data.data);
                                const byteNumbers = new Array(audioData.length);
                                for (let i = 0; i < audioData.length; i++) {
                                    byteNumbers[i] = audioData.charCodeAt(i);
                                }
                                const byteArray = new Uint8Array(byteNumbers);
                                audioQueue.push(byteArray.buffer);
                                if (!isPlaying) playNextChunk();
                            }
                            break;
                        case "audio_end":
                            const finalDisplay = document.getElementById("finalTextDisplay");
                            if (finalDisplay) {
                                finalDisplay.textContent = lastAiMessage || "(No response)";
                            }
                            lastAiMessage = "";
                            break;
                        case "error":
                            statusDisplay.textContent = `Error: ${data.message}`;
                            break;
                    }
                } catch (err) { console.error("Parse error:", err); }
            };

            socket.onclose = () => stopRecording(false);
            socket.onerror = () => stopRecording();

        } catch (err) {
            alert("Failed to start recording.");
            await stopRecording();
        }
    };

    const stopRecording = async (sendEOF = true) => {
        if (!isRecording) return;
        isRecording = false;

        stopCurrentPlayback();
        if (heartbeatInterval) clearInterval(heartbeatInterval);

        if (processor) processor.disconnect();
        if (source) source.disconnect();
        if (recordBtn.mediaStream) {
            recordBtn.mediaStream.getTracks().forEach(track => track.stop());
            recordBtn.mediaStream = null;
        }
        if (socket?.readyState === WebSocket.OPEN) socket.close();
        socket = null;
        updateUIForRecording(false);
    };

    const updateUIForRecording = (isRec) => {
        if (isRec) {
            recordBtn.classList.add("bg-red-600");
            recordBtn.classList.remove("bg-violet-600");
            statusDisplay.textContent = "Connecting...";
            chatDisplay.classList.remove("hidden");
        } else {
            recordBtn.classList.remove("bg-red-600");
            recordBtn.classList.add("bg-violet-600");
            statusDisplay.textContent = "Ready";
        }
    };

    const addToChatLog = (text, sender) => {
        const messageElement = document.createElement("div");
        messageElement.className = 'chat-message';
        const prefixSpan = document.createElement('span');
        const contentSpan = document.createElement('span');
        contentSpan.className = 'message-content';
        if (sender === 'user') {
            prefixSpan.textContent = 'You: ';
        } else {
            prefixSpan.textContent = 'Nova: ';
        }
        contentSpan.textContent = text;
        messageElement.appendChild(prefixSpan);
        messageElement.appendChild(contentSpan);
        chatContainer.appendChild(messageElement);
        chatContainer.scrollTop = chatContainer.scrollHeight;
        return contentSpan;
    };

    clearBtn.addEventListener("click", () => {
        chatContainer.innerHTML = '';
    });

    recordBtn.addEventListener("click", () => {
        if (isRecording) stopRecording();
        else startRecording();
    });

    window.addEventListener('beforeunload', () => {
        if (isRecording) stopRecording();
    });

    async function fetchSkill(skill) {
        let result = "";
        if (skill === "weather") {
            result = "Today's weather: Sunny, 30°C ☀️"; 
        } else if (skill === "news") {
            result = "Breaking News: AI is transforming the world! 📰"; 
        }
        addToChatLog(result, "ai");
    }
});
