package sdkapp

import (
	"context"
	"errors"
	"fmt"
	"net"
	"os"
	"os/user"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"github.com/digital-dream-labs/hugh/grpc/client"
	"github.com/fforchino/vector-go-sdk/pkg/vector"
	"github.com/fforchino/vector-go-sdk/pkg/vectorpb"
	"github.com/kercre123/wire-pod/chipper/pkg/logger"
	"github.com/kercre123/wire-pod/chipper/pkg/vars"
	"golang.org/x/crypto/ssh"
)

var robots []Robot
var timerStopIndexes []int
var inhibitCreation bool

type Robot struct {
	ESN               string
	GUID              string
	Target            string
	Vector            *vector.Vector
	BcAssumption      bool
	CamStreaming      bool
	EventStreamClient vectorpb.ExternalInterface_EventStreamClient
	EventsStreaming   bool
	StimState         float32
	ConnTimer         int32
	Ctx               context.Context
}

func newRobot(serial string) (Robot, int, error) {
	inhibitCreation = true
	var RobotObj Robot

	// generate context
	RobotObj.Ctx = context.Background()

	// find robot info in BotInfo
	matched := false
	for _, robot := range vars.BotInfo.Robots {
		if strings.EqualFold(serial, robot.Esn) {
			RobotObj.ESN = strings.TrimSpace(strings.ToLower(serial))
			RobotObj.Target = robot.IPAddress + ":443"
			matched = true
			if robot.GUID == "" {
				robot.GUID = vars.BotInfo.GlobalGUID
				RobotObj.GUID = vars.BotInfo.GlobalGUID
			} else {
				RobotObj.GUID = robot.GUID
			}
			logger.Println("Connecting to " + serial + " with GUID " + RobotObj.GUID)
		}
	}
	if !matched {
		inhibitCreation = false
		return RobotObj, 0, fmt.Errorf("error: robot not found in SDK info file")
	}

	// create Vector instance
	var err error
	RobotObj.Vector, err = vector.New(
		vector.WithTarget(RobotObj.Target),
		vector.WithSerialNo(RobotObj.ESN),
		vector.WithToken(RobotObj.GUID),
	)
	if err != nil {
		inhibitCreation = false
		return RobotObj, 0, err
	}

	// connection check
	_, err = RobotObj.Vector.Conn.BatteryState(context.Background(), &vectorpb.BatteryStateRequest{})
	if err != nil {
		inhibitCreation = false
		return RobotObj, 0, err
	}

	// create client for event stream
	RobotObj.EventStreamClient, err = RobotObj.Vector.Conn.EventStream(
		RobotObj.Ctx,
		&vectorpb.EventRequest{
			ListType: &vectorpb.EventRequest_WhiteList{
				WhiteList: &vectorpb.FilterList{
					// this will be used only for stimulation graph for now
					List: []string{"stimulation_info"},
				},
			},
		},
	)
	if err != nil {
		inhibitCreation = false
		return RobotObj, 0, err
	}
	RobotObj.CamStreaming = false
	RobotObj.EventsStreaming = false

	// we have confirmed robot connection works, append to list of bots
	robots = append(robots, RobotObj)
	robotIndex := len(robots) - 1

	// begin inactivity timer
	go connTimer(RobotObj.ESN)

	inhibitCreation = false
	return RobotObj, robotIndex, nil
}

func GetRobot(serial string) (Robot, int, error) {
	// look in robot list
	for {
		if !inhibitCreation {
			break
		}
		time.Sleep(time.Second / 2)
	}
	for index, robot := range robots {
		if strings.EqualFold(serial, robot.ESN) {
			_, err := robot.Vector.Conn.BatteryState(context.Background(), &vectorpb.BatteryStateRequest{})
			if err == nil {
				return robot, index, nil
			}
			logger.Println("Cached connection to " + serial + " is dead or unauthenticated: " + err.Error() + ". Reconnecting...")
			removeRobot(serial, "getRobot")
			break
		}
	}
	return newRobot(serial)
}

// if connection is inactive for more than 5 minutes, remove robot
// run this as a goroutine
func connTimer(serial string) {
	connTimerVal := 0
	for {
		time.Sleep(time.Second)
		// Find the robot index dynamically
		found := false
		var ind int
		for i, robot := range robots {
			if strings.EqualFold(robot.ESN, serial) {
				ind = i
				found = true
				break
			}
		}
		if !found {
			logger.Println("Conn timer for " + serial + " exiting (robot removed)")
			return
		}

		// check if timer needs to be stopped
		for _, num := range timerStopIndexes {
			if num == ind {
				logger.Println("Conn timer for robot index " + strconv.Itoa(ind) + " stopping")
				var newIndexes []int
				for _, num := range timerStopIndexes {
					if num != ind {
						newIndexes = append(newIndexes, num)
					}
				}
				timerStopIndexes = newIndexes
				return
			}
		}
		if connTimerVal >= 300 {
			logger.Println("Closing SDK connection for " + robots[ind].ESN + ", source: connTimer")
			removeRobot(robots[ind].ESN, "connTimer")
			return
		}  
		robots[ind].ConnTimer = int32(connTimerVal)
		connTimerVal++
	}
}

func removeRobot(serial, source string) {
	inhibitCreation = true
	var newRobots []Robot
	for ind, robot := range robots {
		if !strings.EqualFold(serial, robot.ESN) {
			newRobots = append(newRobots, robot)
		} else {
			if source == "server" {
				timerStopIndexes = append(timerStopIndexes, ind)
			}
			robots[ind].CamStreaming = false
			robots[ind].EventsStreaming = false
			robots[ind].BcAssumption = false
			// give time for all of that to stop
			time.Sleep(time.Second * 3)
		}
	}
	robots = newRobots
	inhibitCreation = false
}

func NewWP(serial string, useGlobal bool) (*vector.Vector, error) {
	var target, guid string
	if serial == "" {
		return nil, fmt.Errorf("serial string missing")
	}
	matched := false
	for _, robot := range vars.BotInfo.Robots {
		if strings.EqualFold(serial, robot.Esn) {
			matched = true
			target = robot.IPAddress + ":443"
			guid = robot.GUID
			break
		}
	}
	if !matched {
		logger.Println("serial did not match any bot in bot json")
		return nil, errors.New("serial did not match any bot in bot json")
	}
	c, err := client.New(
		client.WithTarget(target),
		client.WithInsecureSkipVerify(),
	)
	if err != nil {
		return nil, err
	}
	if err := c.Connect(); err != nil {
		return nil, err
	}
	c.Close()
	return vector.New(
		vector.WithTarget(target),
		vector.WithSerialNo(serial),
		vector.WithToken(guid),
	)
}

func getRealHomeDir() string {
	sudoUser := os.Getenv("SUDO_USER")
	if sudoUser != "" {
		if u, err := user.Lookup(sudoUser); err == nil {
			return u.HomeDir
		}
	}
	if h := os.Getenv("HOME"); h != "" {
		return h
	}
	return "/root"
}

func SyncVectorHosts() {
	go func() {
		// Wait 5 seconds to let the server start and retrieve outbound IP
		time.Sleep(5 * time.Second)

		home := getRealHomeDir()
		keyPath := filepath.Join(home, "Downloads", "ssh_root_key")
		keyBytes, err := os.ReadFile(keyPath)
		if err != nil {
			logger.Println("Self-healing: SSH root key not found at " + keyPath + ", skipping hosts sync")
			return
		}

		signer, err := ssh.ParsePrivateKey(keyBytes)
		if err != nil {
			logger.Println("Self-healing: Failed to parse SSH key: " + err.Error())
			return
		}

		config := &ssh.ClientConfig{
			User: "root",
			Auth: []ssh.AuthMethod{
				ssh.PublicKeys(signer),
			},
			HostKeyCallback:   ssh.InsecureIgnoreHostKey(),
			HostKeyAlgorithms: []string{"ssh-rsa", "ecdsa-sha2-nistp256"},
			Timeout:           5 * time.Second,
		}

		macIP := vars.GetOutboundIP().String()

		for _, robot := range vars.BotInfo.Robots {
			if robot.IPAddress == "" {
				continue
			}
			logger.Println("Self-healing: Attempting to sync escapepod.local IP on Vector " + robot.Esn + " (" + robot.IPAddress + ")")
			client, err := ssh.Dial("tcp", robot.IPAddress+":22", config)
			if err != nil {
				logger.Println("Self-healing: Failed to connect to Vector via SSH: " + err.Error())
				continue
			}

			session, err := client.NewSession()
			if err != nil {
				client.Close()
				continue
			}

			cmd := fmt.Sprintf("mount -o rw,remount / && sed -i '/escapepod.local/d' /etc/hosts && echo '%s escapepod.local' >> /etc/hosts", macIP)
			err = session.Run(cmd)
			if err != nil {
				logger.Println("Self-healing: Failed to update hosts file on Vector: " + err.Error())
			} else {
				logger.Println("Self-healing: Successfully updated escapepod.local IP to " + macIP + " on Vector " + robot.Esn)
			}
			session.Close()
			client.Close()
		}
	}()
}

func init() {
	StartWifiKeepAlive()
	SyncVectorHosts()
}

func StartWifiKeepAlive() {
	go func() {
		for {
			time.Sleep(10 * time.Second)
			for _, robot := range vars.BotInfo.Robots {
				if robot.IPAddress != "" {
					conn, err := net.DialTimeout("tcp", robot.IPAddress+":443", 2*time.Second)
					if err == nil {
						conn.Close()
					}
				}
			}
		}
	}()
}
