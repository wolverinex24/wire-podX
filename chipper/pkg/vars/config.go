package vars

import (
	"encoding/json"
	"os"
	"strings"
	"unicode"

	"github.com/kercre123/wire-pod/chipper/pkg/logger"
)

// a way to create a JSON configuration for wire-pod, rather than the use of env vars

var ApiConfigPath = "./apiConfig.json"

var APIConfig apiConfig

type apiConfig struct {
	Weather struct {
		Enable   bool   `json:"enable"`
		Provider string `json:"provider"`
		Key      string `json:"key"`
		Unit     string `json:"unit"`
	} `json:"weather"`
	Knowledge struct {
		Enable                 bool    `json:"enable"`
		Provider               string  `json:"provider"`
		Key                    string  `json:"key"`
		ID                     string  `json:"id"`
		Model                  string  `json:"model"`
		IntentGraph            bool    `json:"intentgraph"`
		RobotName              string  `json:"robotName"`
		OpenAIPrompt           string  `json:"openai_prompt"`
		OpenAIVoice            string  `json:"openai_voice"`
		OpenAIVoiceWithEnglish bool    `json:"openai_voice_with_english"`
		SaveChat               bool    `json:"save_chat"`
		CommandsEnable         bool    `json:"commands_enable"`
		Endpoint               string  `json:"endpoint"`
		TopP                   float32 `json:"top_p"`
		Temperature            float32 `json:"temp"`
	} `json:"knowledge"`
	STT struct {
		Service         string `json:"provider"`
		Language        string `json:"language"`
		FallbackService string `json:"fallback_provider"`
		Groq            struct {
			APIKey   string `json:"api_key"`
			Model    string `json:"model"`
			Language string `json:"language"`
			Prompt   string `json:"prompt"`
			Endpoint string `json:"endpoint"`
		} `json:"groq"`
	} `json:"STT"`
	Server struct {
		// false for ip, true for escape pod
		EPConfig bool   `json:"epconfig"`
		Port     string `json:"port"`
	} `json:"server"`
	HasReadFromEnv   bool `json:"hasreadfromenv"`
	PastInitialSetup bool `json:"pastinitialsetup"`
}

func IsLocalSTTService(service string) bool {
	return service == "vosk" || service == "whisper.cpp"
}

func UsesVoskFallback() bool {
	return APIConfig.STT.Service == "vosk" || APIConfig.STT.Service == "groq" || APIConfig.STT.Service == "whisper.cpp"
}

func ActiveLocalSTTService() string {
	if IsLocalSTTService(APIConfig.STT.Service) {
		return APIConfig.STT.Service
	}
	if APIConfig.STT.Service == "groq" && IsLocalSTTService(APIConfig.STT.FallbackService) {
		return APIConfig.STT.FallbackService
	}
	return ""
}

func UsesLocalSTTLanguage() bool {
	return ActiveLocalSTTService() != ""
}

func normalizeSTTConfig() {
	if (APIConfig.STT.Service == "groq" || APIConfig.STT.Service == "whisper.cpp") && !IsLocalSTTService(APIConfig.STT.FallbackService) {
		APIConfig.STT.FallbackService = "vosk"
	}
}

func sanitizeConfig() {
	APIConfig.Knowledge.Key = strings.TrimFunc(APIConfig.Knowledge.Key, unicode.IsSpace)
	APIConfig.Knowledge.Endpoint = strings.TrimFunc(APIConfig.Knowledge.Endpoint, unicode.IsSpace)
	APIConfig.STT.Groq.APIKey = strings.TrimFunc(APIConfig.STT.Groq.APIKey, unicode.IsSpace)
}

func WriteConfigToDisk() {
	sanitizeConfig()
	logger.Println("Configuration changed, writing to disk")
	writeBytes, _ := json.Marshal(APIConfig)
	os.WriteFile(ApiConfigPath, writeBytes, 0644)
}

func CreateConfigFromEnv() {
	// if no config exists, create it
	if os.Getenv("WEATHERAPI_ENABLED") == "true" {
		APIConfig.Weather.Enable = true
		APIConfig.Weather.Provider = os.Getenv("WEATHERAPI_PROVIDER")
		APIConfig.Weather.Key = os.Getenv("WEATHERAPI_KEY")
		APIConfig.Weather.Unit = os.Getenv("WEATHERAPI_UNIT")
	} else {
		APIConfig.Weather.Enable = false
	}
	if os.Getenv("KNOWLEDGE_ENABLED") == "true" {
		APIConfig.Knowledge.Enable = true
		APIConfig.Knowledge.Provider = os.Getenv("KNOWLEDGE_PROVIDER")
		if os.Getenv("KNOWLEDGE_PROVIDER") == "houndify" {
			APIConfig.Knowledge.ID = os.Getenv("KNOWLEDGE_ID")
		}
		APIConfig.Knowledge.Key = os.Getenv("KNOWLEDGE_KEY")
	} else {
		APIConfig.Knowledge.Enable = false
	}
	WriteSTT()
	APIConfig.HasReadFromEnv = true
	writeBytes, _ := json.Marshal(APIConfig)
	os.WriteFile(ApiConfigPath, writeBytes, 0644)
}

func WriteSTT() {
	// was not part of the original code, so this is its own function
	// launched if stt not found in config
	APIConfig.STT.Service = os.Getenv("STT_SERVICE")
	APIConfig.STT.FallbackService = os.Getenv("STT_FALLBACK_SERVICE")
	if (APIConfig.STT.Service == "groq" || APIConfig.STT.Service == "whisper.cpp") && APIConfig.STT.FallbackService == "" {
		APIConfig.STT.FallbackService = "vosk"
	}
	if UsesLocalSTTLanguage() {
		APIConfig.STT.Language = os.Getenv("STT_LANGUAGE")
	}
	APIConfig.STT.Groq.APIKey = os.Getenv("GROQ_API_KEY")
	APIConfig.STT.Groq.Model = os.Getenv("GROQ_STT_MODEL")
	APIConfig.STT.Groq.Language = os.Getenv("GROQ_STT_LANGUAGE")
	APIConfig.STT.Groq.Prompt = os.Getenv("GROQ_STT_PROMPT")
	APIConfig.STT.Groq.Endpoint = os.Getenv("GROQ_API_URL")
}

func ReadConfig() {
	if _, err := os.Stat(ApiConfigPath); err != nil {
		CreateConfigFromEnv()
		logger.Println("API config JSON created")
	} else {
		// read config
		configBytes, err := os.ReadFile(ApiConfigPath)
		if err != nil {
			APIConfig.Knowledge.Enable = false
			APIConfig.Weather.Enable = false
			logger.Println("Failed to read API config file")
			logger.Println(err)
			return
		}
		err = json.Unmarshal(configBytes, &APIConfig)
		if err != nil {
			APIConfig.Knowledge.Enable = false
			APIConfig.Weather.Enable = false
			logger.Println("Failed to unmarshal API config JSON")
			logger.Println(err)
			return
		}
		sanitizeConfig()
		// stt service is the only thing controlled by shell
		if APIConfig.STT.Service != os.Getenv("STT_SERVICE") {
			WriteSTT()
		}
		normalizeSTTConfig()
		if !APIConfig.HasReadFromEnv {
			if APIConfig.Server.Port != os.Getenv("DDL_RPC_PORT") {
				APIConfig.HasReadFromEnv = true
				APIConfig.PastInitialSetup = true
			}
		}

		if APIConfig.Knowledge.Model == "meta-llama/Llama-2-70b-chat-hf" {
			logger.Println("Setting Together model to Llama3")
			APIConfig.Knowledge.Model = "meta-llama/Llama-3-70b-chat-hf"
		}

		writeBytes, _ := json.Marshal(APIConfig)
		os.WriteFile(ApiConfigPath, writeBytes, 0644)
		logger.Println("API config successfully read")
	}
}
