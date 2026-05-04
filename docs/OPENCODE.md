# Using OpenCode with this server

The bundled vLLM wheel serves API endpoints that OpenCode can talk to without problems. No proxy, no LiteLLM, no translation layer.

## Quick start

1. Start the server. Pick any snapshot in the launcher (the default is
   `start_72tps` on port 5001), or run headless:

   ```powershell
   start.bat --headless --snapshot start_72tps
   ```

   Wait until the log shows `Application startup complete.`

2. If you have freshly installed OpenCode, then launch it once first to get the local directories 
   to be created, and then make an 'opencode.json' file in that directory
   
   The directory is located at `~/.config/opencode/opencode.json` (or `%USERPROFILE%\.config\opencode\opencode.json`
   on Windows): 

   Then put these contents into the opencode.json file:

   ```json
	   {
	  "$schema": "https://opencode.ai/config.json",
	  "provider": {
	    "vllm-local": {
	      "npm": "@ai-sdk/openai-compatible",
	      "name": "Local vLLM",
	      "options": {
	        "baseURL": "http://localhost:5001/v1",
	        "apiKey": "sk-no-key-required"
	      },
	      "models": {
	        "your-vllm-model-name": {
	          "name": "Local Qwen3",
			   "limit": {
	            "context": 90000,
	            "output": 8192
			   }
	        }
	      }
	    }
	  },
	  "model": "vllm-local/your-vllm-model-name"
	}
	```

3. Run `Opencode` in your project. It shiould hit your local server.

4. I highly recommend also adding an AGENTS.MD file in the same directory, with instructions to help OpenCode with tool calling. The instructions are "I am on Windows operating system. When creating or editing files, ALWAYS use double backslashes (e.g., C:\\path\\to\\file) in your tool calls. Do not use forward slashes or single backslashes"
