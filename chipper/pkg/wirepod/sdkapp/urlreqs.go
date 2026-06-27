package sdkapp

import (
	"bytes"
	"crypto/tls"
	"net/http"

	"github.com/kercre123/wire-pod/chipper/pkg/logger"
)

var transCfg = &http.Transport{
	TLSClientConfig: &tls.Config{InsecureSkipVerify: true}, // ignore SSL warnings
}

func setCustomEyeColor(robot Robot, hue string, sat string) {
	url := "https://" + robot.Target + "/v1/update_settings"
	var updateJSON = []byte(`{"update_settings": true, "settings": {"custom_eye_color": {"enabled": true, "hue": ` + hue + `, "saturation": ` + sat + `} } }`)
	req, _ := http.NewRequest("POST", url, bytes.NewBuffer(updateJSON))
	req.Header.Set("Authorization", "Bearer "+robot.GUID)
	req.Header.Set("Content-Type", "application/json")
	client := &http.Client{Transport: transCfg}
	resp, err := client.Do(req)
	if err != nil {
		logger.Println("setCustomEyeColor error: " + err.Error())
		return
	}
	defer resp.Body.Close()
}

func setPresetEyeColor(robot Robot, value string) {
	url := "https://" + robot.Target + "/v1/update_settings"
	var updateJSON = []byte(`{"update_settings": true, "settings": {"custom_eye_color": {"enabled": false}, "eye_color": ` + value + `} }`)
	req, _ := http.NewRequest("POST", url, bytes.NewBuffer(updateJSON))
	req.Header.Set("Authorization", "Bearer "+robot.GUID)
	req.Header.Set("Content-Type", "application/json")
	client := &http.Client{Transport: transCfg}
	resp, err := client.Do(req)
	if err != nil {
		logger.Println("setPresetEyeColor error: " + err.Error())
		return
	}
	defer resp.Body.Close()
}

func setSettingSDKstring(robot Robot, setting string, value string) {
	url := "https://" + robot.Target + "/v1/update_settings"
	var updateJSON = []byte(`{"update_settings": true, "settings": {"` + setting + `": "` + value + `" } }`)
	req, _ := http.NewRequest("POST", url, bytes.NewBuffer(updateJSON))
	req.Header.Set("Authorization", "Bearer "+robot.GUID)
	req.Header.Set("Content-Type", "application/json")
	client := &http.Client{Transport: transCfg}
	resp, err := client.Do(req)
	if err != nil {
		logger.Println("setSettingSDKstring error: " + err.Error())
		return
	}
	defer resp.Body.Close()
}

func setSettingSDKintbool(robot Robot, setting string, value string) {
	url := "https://" + robot.Target + "/v1/update_settings"
	var updateJSON = []byte(`{"update_settings": true, "settings": {"` + setting + `": ` + value + ` } }`)
	req, _ := http.NewRequest("POST", url, bytes.NewBuffer(updateJSON))
	req.Header.Set("Authorization", "Bearer "+robot.GUID)
	req.Header.Set("Content-Type", "application/json")
	client := &http.Client{Transport: transCfg}
	resp, err := client.Do(req)
	if err != nil {
		logger.Println("setSettingSDKintbool error: " + err.Error())
		return
	}
	defer resp.Body.Close()
}
