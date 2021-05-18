"""
This file contains the implementation of the environment from the point
of view of a single agent. The environment class SingleRLAgent embeds
three subclasses (FingerLayer, ExternalRepresentation, OtherInteractions)
which implement the dynamics of the different environment parts.
"""
import random
import time

import numpy as np
import torch

from IPython.display import display
from PIL import Image

from src import utils


# TODO (?): later in utils
# from fonts.ttf import AmaticSC


class SingleAgentEnv:
    """
    This class implements the environment as a whole.
    """

    def __init__(self, agent_params):
        model = None
        self.CL = False  # using Curriculum Learning

        # allows fair label comparison in Curriculum Learning:
        # (when we have CL the agent starts with the possibility
        # to output labels for numerosities greater than the ones
        # it has already seen in the beginning)
        if 'max_CL_objects' in agent_params:
            self.CL = True
            self.max_CL_objects = agent_params['max_CL_objects']
        self.max_objects = agent_params['max_objects']
        self.obs_dim = agent_params['obs_dim']
        self.actions_dict = {n: '' for n in range(agent_params['n_actions'])}
        self.max_episode_length = agent_params['max_episode_length']

        # Initialize observation: 1-max_objects randomly placed
        # 1s placed on a 0-grid of shape dim x dim
        self.obs = np.zeros((self.obs_dim, self.obs_dim))
        ones_mask = np.random.choice(self.obs.size,
                                     self.max_objects,
                                     replace=False)
        self.obs.ravel()[ones_mask] = 1
        # associated label
        num_objects = self.obs.sum(dtype=int)
        if self.CL:
            self.obs_label = np.zeros(self.max_CL_objects)
        else:
            self.obs_label = np.zeros(self.max_objects)
        self.obs_label[num_objects - 1] = 1

        # Initialize external representation
        # (the piece of paper the agent is writing on)
        self.ext_repr = ExternalRepresentation(self.obs_dim, self.actions_dict)

        # Initialize Finger layers: Single 1 in 0-grid of shape dim x dim
        self.finger_layer_scene = FingerLayer(self.obs_dim, self.actions_dict)
        self.finger_layer_repr = FingerLayer(self.obs_dim, self.actions_dict)

        # Fill actions dict empty positions (number labels)
        label = 1
        for k in self.actions_dict:
            if self.actions_dict[k] == '':
                self.actions_dict[k] = str(label)
                label += 1

        # Initialize whole state space:
        # concatenated observation & external representation
        self.build_state()

        # Initialize other interactions: e.g. 'submit', 'larger'/'smaller,
        # self.otherinteractions = OtherInteractions(len(self.actions_dict), self.actions_dict)

        # Initialize action vector
        self.action_vec = np.zeros((len(self.actions_dict), 1))

        # Initialize neural network model: maps observation-->action
        self.model = model
        self.fps_inv = 500  # ms
        self.is_submitted_ext_repr = False
        self.submitted_ext_repr = None

        # Initialize counter of steps in the environment with this scene
        self.step_counter = 0

    def step(self, q_values, n_iter, visit_history):
        # Define how action interacts with environment:
        # e.g. with observation space and external representation

        done = False  # signal episode ending
        self.step_counter += 1
        # TODO: reward when finger on object?

        # action = self.eps_greedy_modified(q_values) # TODO: generalize
        if n_iter < 2000:
            # follow exploration profiles for the first 1k iters
            tau = self.get_tau(n_iter)
        else:
            tau = 0  # then choose according to the q-values only

        action = self.softmax_action_selection(q_values, tau)

        if action in self.finger_layer_scene.action_codes:
            self.finger_layer_scene.step(action, self.actions_dict)

        elif action in self.finger_layer_repr.action_codes:
            self.finger_layer_repr.step(action, self.actions_dict)

        # For action on external representation:
        # Give as argument: either pixel-positions (1D or 2D) to draw on,
        # or draw_point/not-draw at the current finger-position
        elif action in self.ext_repr.action_codes:
            x = self.finger_layer_repr.pos_x
            y = self.finger_layer_repr.pos_y
            self.ext_repr.draw_point([x, y])

        # elif(action in self.otherinteractions.action_codes):
        # self.otherinteractions.step(action, self.max_objects, self.obs_label)
        # done = True

        reward = self.get_reward(action, visit_history)

        # new episode ending logic: if label is correct or
        # the episode lasted too long
        if (reward == 1) or (self.step_counter > self.max_episode_length):
            done = True

        # Build action-array according to the int/string action.
        # This is mainly for the demo mode, where actions are given
        # manually by str/int. When trained action-array is input.
        self.action_vec = np.zeros((len(self.actions_dict), 1))
        self.action_vec[action] = 1

        self.build_state()

        return torch.Tensor(self.state), reward, done, 'info'

    @staticmethod
    def get_tau(n_iter):
        initial_value = 5
        num_iterations = 1000
        # We compute the exponential decay in such a way the shape of the
        # exploration profile does not depend on the number of iterations
        exp_decay = np.exp(-np.log(
            initial_value) / num_iterations * 6)
        return initial_value * (exp_decay ** n_iter)

    def softmax_action_selection(self, q_values, temperature):
        """
        Args:
            - q_values: output of the network
            - temperature: value of temperature parameter of the softmax function
        """

        if temperature < 0:
            raise Exception('The temperature value must be greater than or equal to 0 ')

        # If the temperature is 0, just select the best action
        # using the eps-greedy policy with epsilon = 0
        if temperature == 0:
            return self.eps_greedy_modified(q_values, 0)

        # Apply softmax with temp
        # set a minimum to the temperature for numerical stability
        temperature = max(temperature, 1e-8)
        softmax = torch.nn.Softmax(dim=1)
        softmax_out = softmax(- q_values / temperature).squeeze()

        # Sample the action using softmax output as mass pdf
        all_possible_actions = np.arange(0, softmax_out.shape[-1])
        # this samples a random element from "all_possible_actions"
        # with the probability distribution p (softmax_out in this case)
        action = np.random.choice(all_possible_actions, p=softmax_out.numpy())

        return action

    def eps_greedy_modified(self, q_values, eps=.1):
        # TODO: eps not-hardcoded

        n_actions = len(self.actions_dict)

        sample = random.random()
        if sample > eps:
            action = q_values.max(1)[1].item()
            # max(1) is for batch, [1] is for index, .item() is for scalar
        else:
            action = random.randrange(n_actions)

        return action

    def render(self, display_id=None):
        img_height = 200
        self.obs_img = Image.fromarray(self.obs * 255).resize((img_height, img_height), resample=0)
        self.obs_img = utils.add_grid_lines(self.obs_img, self.obs)
        self.obs_img = self.obs_img.transpose(Image.TRANSPOSE)
        self.obs_img = utils.annotate_below(self.obs_img, "Observation")

        self.action_img = Image.fromarray(self.action_vec * 255
                                          ).resize((int(img_height / 4), img_height), resample=0)
        self.action_img = utils.add_grid_lines(self.action_img, np.reshape(self.action_vec, (-1, 1)))
        self.action_img = utils.annotate_nodes(self.action_img, list(self.actions_dict.values()))
        self.action_img = utils.annotate_below(self.action_img, "Action")

        self.ext_repr_img = Image.fromarray(self.ext_repr.external_representation *
                                            255).resize((img_height, img_height), resample=0)
        self.ext_repr_img = utils.add_grid_lines(self.ext_repr_img, self.ext_repr.external_representation)
        self.ext_repr_img = self.ext_repr_img.transpose(Image.TRANSPOSE)
        self.ext_repr_img = utils.annotate_below(self.ext_repr_img, "External representation")

        self.finger_scene_img = Image.fromarray(self.finger_layer_scene.fingerlayer * 255).resize(
            (img_height, img_height), resample=0)
        self.finger_scene_img = utils.add_grid_lines(self.finger_scene_img, self.finger_layer_scene.fingerlayer)
        self.finger_scene_img = self.finger_scene_img.transpose(Image.TRANSPOSE)
        self.finger_scene_img = utils.annotate_below(self.finger_scene_img, "Finger layer scene")

        self.finger_repr_img = Image.fromarray(self.finger_layer_repr.fingerlayer * 255
                                               ).resize((img_height, img_height), resample=0)
        self.finger_repr_img = utils.add_grid_lines(self.finger_repr_img, self.finger_layer_repr.fingerlayer)
        self.finger_repr_img = self.finger_repr_img.transpose(Image.TRANSPOSE)
        self.finger_repr_img = utils.annotate_below(self.finger_repr_img, "Finger layer repr.")

        total_img = utils.concat_imgs_h(
            [self.obs_img, self.finger_scene_img, self.finger_repr_img, self.ext_repr_img, self.action_img],
            dist=10).convert('RGB')

        if display_id is not None:
            display(total_img, display_id=display_id)
            time.sleep(self.fps_inv)

        return total_img

    def reset(self):
        # generate new observation
        self.obs = np.zeros((self.obs_dim, self.obs_dim))
        self.obs.ravel()[np.random.choice(self.obs.size, self.max_objects, replace=False)] = 1
        # associated label
        num_objects = self.obs.sum(dtype=int)
        if self.CL:
            self.obs_label = np.zeros(self.max_CL_objects)
        else:
            self.obs_label = np.zeros(self.max_objects)
        self.obs_label[num_objects - 1] = 1  # vector form

        # reset external representation
        self.ext_repr = ExternalRepresentation(self.obs_dim, self.actions_dict)

        # Initialize Finger layers: Single 1 in 0-grid of shape dim x dim
        self.finger_layer_scene = FingerLayer(self.obs_dim, self.actions_dict)
        self.finger_layer_repr = FingerLayer(self.obs_dim, self.actions_dict)

        # reset whole state
        self.build_state()

        # reset counter of steps in an environment with a given scene
        self.step_counter = 0

        return torch.Tensor(self.state)

    def build_state(self):
        self.state = np.stack([[self.obs,
                                self.finger_layer_scene.fingerlayer,
                                self.finger_layer_repr.fingerlayer, self.ext_repr.external_representation]])

    @staticmethod
    def compare_labels(agent_label, true_label) -> int:
        """Encode here the label comparison dynamics.
        """
        if len(agent_label) != len(true_label):
            print("Agent label and true label have different sizes.")
        label_dist = np.abs(np.argmax(agent_label) - np.argmax(true_label))

        return label_dist

    def get_reward(self, action: int, visit_history: dict) -> float:
        """Reward function. Currently implementing only label-based reward
        logic, giving positive reward when the action is a label action
        which corresponds to the correct label. We can also give a negative
        reward to the agent when it outputs the wrong label.
        We can implement a simple curiosity mechanism, saving
        the number of times the agent has been in each different state.
        """
        n_actions = len(self.actions_dict)
        if self.CL:
            start_labels_actions = n_actions - self.max_CL_objects
        else:
            start_labels_actions = n_actions - self.max_objects

        reward = 0

        if action in range(start_labels_actions, n_actions):
            chosen_label = int(self.actions_dict[action])
            true_label = np.argmax(self.obs_label) + 1

            if chosen_label == true_label:
                reward = 1
            else:
                reward = -.5

        # implementing a simple curiosity mechanism
        current_state_hash = self.get_state_hash()
        n_visits = visit_history.get(current_state_hash, 0)
        if n_visits == 0:
            reward += .1

        visit_history.setdefault(current_state_hash, 0)
        visit_history[current_state_hash] += 1

        return reward

        # in case we want to keep label distance-based rewards...
        # label_dist = self.compare_labels(label_slice, self.obs_label)

        # reward based on scene finger position
        # finger_index = self.fingerlayer_scene.fingerlayer.argmax()
        # finger_position = np.unravel_index(finger_index, self.fingerlayer_scene.fingerlayer.shape)

        # if self.obs[finger_position] == 1:
        # reward += 0.1 # TODO: diminishing reward?

        # TODO: reward diminishing with time

        # TODO: reward showing how to create repr. for small quantities

    def get_state_hash(self):
        flattened_state = self.state.flatten()
        string_state = ''.join([str(v) for v in flattened_state])
        return hash(string_state)

    @staticmethod
    def get_curiosity_reward(n_visits: int, bending=.4, scale=.1) -> float:
        # the greater the bending parameter, the less bended is the curve
        # the greater the scale parameter, the larger the scale of the curve
        # with the default parameters, the prize for unvisited states is .1
        return (bending / (bending + n_visits)) * scale


class FingerLayer:
    """
    This class implements the finger movement part of the environment.
    """

    def __init__(self, layer_dim, env_actions_dict):
        self.layer_dim = layer_dim
        self.fingerlayer = np.zeros((layer_dim, layer_dim))
        self.max_x = layer_dim - 1
        self.max_y = layer_dim - 1
        self.pos_x = random.randint(0, layer_dim - 1)
        self.pos_y = random.randint(0, layer_dim - 1)
        self.fingerlayer[self.pos_x, self.pos_y] = 1

        actions = ['left', 'right', 'up', 'down']
        self.action_codes = set()

        # this loop inserts an action in the general env_actions_dict
        # as soon as there is a free spot and as long as there are actions
        # to insert for this part of the environment
        i = 0
        for k, v in env_actions_dict.items():
            if v == '' and i < len(actions):
                env_actions_dict[k] = actions[i]
                self.action_codes.add(k)
                i += 1

    def step(self, move_action, actions_dict):
        move_action_str = actions_dict[move_action]
        if move_action_str == "right":
            if self.pos_x < self.max_x:
                self.pos_x += 1
        elif move_action_str == "left":
            if self.pos_x > 0:
                self.pos_x -= 1
        elif move_action_str == "up":
            if self.pos_y > 0:
                self.pos_y -= 1
        elif move_action_str == "down":
            if self.pos_y < self.max_y:
                self.pos_y += 1
        self.fingerlayer = np.zeros((self.layer_dim, self.layer_dim))
        self.fingerlayer[self.pos_x, self.pos_y] = 1


class ExternalRepresentation:
    """
    This class implements the external representation in the environment.
    """

    def __init__(self, layer_dim, env_actions_dict):
        self.layer_dim = layer_dim
        self.external_representation = np.zeros((layer_dim, layer_dim))

        actions = ['mod_point']
        self.action_codes = set()

        i = 0
        for k, v in env_actions_dict.items():
            if v == '' and i < len(actions):
                env_actions_dict[k] = actions[i]
                self.action_codes.add(k)
                i += 1

    def draw(self, draw_pixels):
        self.external_representation += draw_pixels

    def draw_point(self, pos):
        # This line implements if ext_repr[at_curr_pos]==0 --> set it to 1.
        # if==1 leave it like that.
        self.external_representation[pos[0], pos[1]] += abs(self.external_representation[pos[0], pos[1]] - 1)
