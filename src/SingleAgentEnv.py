"""
This file contains the implementation of the environment from the point
of view of a single agent. The environment class SingleRLAgent embeds
three subclasses (FingerLayer, ExternalRepresentation, OtherInteractions)
which implement the dynamics of the different environment parts.
"""
import random
import time
import warnings

import numpy as np
import src.Reward
import torch

from IPython.display import display
from itertools import product
from PIL import Image

from src import utils


# TODO (?): later in utils
# from fonts.ttf import AmaticSC


class SingleAgentEnv(object):
    """
    This class implements the environment as a whole.
    """

    def __init__(self, reward: src.Reward.Reward,
                 max_CL_objects: int, CL_phases: int,
                 max_episode_objects: int, obs_dim: int,
                 max_episode_length: int, n_actions: int,
                 n_episodes_per_phase: int,
                 max_object_size: int,
                 default_eps: float = .1,
                 exp_dec_steepness: int = 10,
                 generate_random_nobj: bool = True,
                 random_object_size: bool = True,
                 random_finger_position: bool = False,
                 exponential_decay: bool = False):
        """
        This method initializes the environment.

        Args:
            reward: An instance of the Reward class.
            max_CL_objects: the maximum number of objects that
                the agent will observe in the whole CL experience.
            CL_phases: the number of CL phases.
            max_episode_objects: the maximum number of objects that
                the agent can observe in the current episode.
            obs_dim: the length of the side of the (squared)
                observation.
            max_episode_length: the maximum duration of an episode.
            n_actions: the size of the action space.
            n_episodes_per_phase: the maximum number of episodes in
                a CL phase.
            max_object_size: the maximum object size used when
                spawining objects of random size.
            default_eps: fixed value for the episilon parameter in the
                epsilon greedy policy when exponential_decay is False
            exp_dec_steepness: value that regulates the steepness of the
                exponential decay profile curve (higher steeper)
            generate_random_nobj: whether a random number of objects
                should be generated in each episode.
            random_object_size: whether the size of each newly
                generated object should be determined randomly.
            random_finger_position: whether the fingers should be
                placed in random positions in the scene at the
                beginning of an episode.
            exponential_decay: whether an exponential decay profile
                for the value of epsilon parameter in the epsilon greedy
                policy should be used.
        """

        self.max_CL_objects             = max_CL_objects
        self.CL_phases                  = CL_phases
        self.max_episode_objects        = max_episode_objects
        self.obs_dim                    = obs_dim
        self.max_episode_length         = max_episode_length
        self.n_actions                  = n_actions
        self.n_episodes_per_phase       = n_episodes_per_phase
        self.max_object_size            = max_object_size
        self.default_eps                = default_eps
        self.exp_dec_steepness          = exp_dec_steepness
        self.generate_random_nobj       = generate_random_nobj
        self.random_object_size         = random_object_size
        self.random_finger_position     = random_finger_position
        self.exponential_decay          = exponential_decay

        self.max_train_iters = (self.CL_phases * self.n_episodes_per_phase *
                                self.max_episode_length)

        # max_CL_objects allows fair label comparison in Curriculum Learning:
        # (when we have CL the agent starts with the possibility
        # to output labels for numerosities greater than the ones
        # it has already seen in the beginning)
        if self.max_CL_objects is not None:
            self.CL = True
        else:
            self.CL = False

        self.actions_dict = {n: '' for n in range(self.n_actions)}

        self.reward = reward

        self._generate_observation()

        # Initialize external representation
        # (the piece of paper the agent is writing on)
        self.ext_repr = ExternalRepresentation(self.obs_dim, self.actions_dict)

        # Initialize Finger layers: Single 1 in 0-grid of shape dim x dim
        self.finger_layer_scene = FingerLayer(
            'scene',
            self.obs_dim,
            self.actions_dict,
            self.random_finger_position
        )
        self.finger_layer_repr = FingerLayer(
            'repr',
            self.obs_dim,
            self.actions_dict,
            self.random_finger_position
        )

        # Fill actions dict empty positions (number labels)
        label = 1
        for k in self.actions_dict:
            if self.actions_dict[k] == '':
                self.actions_dict[k] = str(label)
                label += 1

        # Initialize whole state space:
        # concatenated observation & external representation
        self._build_state()

        # Initialize other interactions: e.g. 'submit', 'larger'/'smaller,
        # self.otherinteractions = OtherInteractions(len(self.actions_dict), self.actions_dict)

        # Initialize action vector
        self.action_vec = np.zeros((len(self.actions_dict), 1))

        # Initialize neural network model: maps observation-->action
        self.fps_inv = 500  # ms
        self.is_submitted_ext_repr = False
        self.submitted_ext_repr = None

        # Initialize counter of steps in the environment with this scene
        self.step_counter = 0

        # Initialize flag for label output
        # the agent gets positive reward only the first time
        # it outputs a label and it is correct
        self.first_label_output = True

    def step(self, q_values, n_episode, visit_history):
        # Define how action interacts with environment:
        # e.g. with observation space and external representation

        done = False  # signal episode ending
        self.step_counter += 1

        # tau = self.get_tau(n_iter_cl_phase, self.max_train_iters)
        # action = self.softmax_action_selection(q_values, tau)
        if self.exponential_decay:
            eps = self._get_exp_decaying_eps(n_episode)
            # set limit
            eps = max(eps, 1e-6)
        else:
            eps = self.default_eps

        action = self._epsilon_greedy_action_selection(q_values, eps=eps)

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

        reward, correct_label = self.reward.get_reward(self, action, visit_history)

        # new episode ending logic: if label is correct or
        # the episode lasted too long
        if correct_label or (self.step_counter >= self.max_episode_length):
            done = True

        # visualize the shape of the decay
        if (n_episode % 1000 == 0) and not done:
            print(f"{eps=}")

        # Build action-array according to the int/string action.
        # This is mainly for the demo mode, where actions are given
        # manually by str/int. When trained action-array is input.
        self.action_vec = np.zeros((len(self.actions_dict), 1))
        self.action_vec[action] = 1

        self._build_state()

        return action, torch.Tensor(self.state), reward, done, correct_label

    @staticmethod
    def get_tau(n_iter, num_iterations):
        initial_value = 5
        # We compute the exponential decay in such a way the shape of the
        # exploration profile does not depend on the number of iterations
        exp_decay = np.exp(-np.log(
            initial_value) / num_iterations * 6)
        return initial_value * (exp_decay ** n_iter)

    def _get_exp_decaying_eps(self, n_episode):
        exp_decay = np.exp(-np.log(self.exp_dec_steepness) / self.n_episodes_per_phase * 6)
        return (self.exp_dec_steepness * (exp_decay ** n_episode)) / self.exp_dec_steepness

    def _generate_label(self):
        # generate label associated with observation
        self.obs_label = self.obs.sum(dtype=int)

    def _generate_observation(self):
        """
        The mehtod creates the scene observed by the agent in the
        current episode. Different levels of variability in the
        creation of the scene are allowed:
        - the position of the objects can be random or fixed;
        - the size of the squared objects can be random or fixed.

        The method internally checks that it is possible to spawn a new
        object of the desired dimension in the current scene. If it's
        not, the dimension is diminished by 1, until 0 is reached (in
        which case a warining is raised and the objects spawning is
        interrupted.)

        The generated objects are also guaranteed not to overlap
        and not to be adjacent.
        """
        # a flag signaling that the scene generation process
        # ended sooner than expected
        early_ending = False

        # generate new observation
        # k objects (k chosen randomly in [1, max_objects])
        # randomly placed on a 0-grid of shape dim x dim
        picture_objects_coordinates = set()

        self.obs = np.zeros((self.obs_dim, self.obs_dim))
        if self.generate_random_nobj:
            n_objects = np.random.randint(self.max_episode_objects) + 1
        else:
            n_objects = self.max_episode_objects

        # counter of the number of objects actually drawn
        objects_drawn = n_objects

        for n in range(1, n_objects + 1):
            if early_ending:
                break

            valid_object_size = False

            # choose object size
            if self.random_object_size:
                object_size = np.random.randint(self.max_object_size) + 1
            else:
                object_size = 1

            while not valid_object_size:
                # check it's possible to generate an object
                # of the chosen size in the current scene
                if self._check_square_can_fit(object_size,
                                              picture_objects_coordinates):

                    valid_object_size = True
                    valid_picture = False

                    # attempt at generating a new object in
                    # a valid random position
                    while not valid_picture:
                        object_coordinates = self._generate_square(object_size,
                                                                   picture_objects_coordinates)
                        valid_picture = not self._check_squares_intersection_adjacency(picture_objects_coordinates,
                                                                                       object_coordinates)
                        if valid_picture:
                            picture_objects_coordinates |= object_coordinates

                # reduce object size if not possible
                else:
                    object_size -= 1

                    # until the size reaches 0
                    if object_size == 0:
                        early_ending = True
                        objects_drawn -= (n_objects - n) + 1
                        warnings.warn(
                            "No space left in the scene to draw a square of"
                            f"shape (1,1). {n - 1} objects drawn."
                        )
                        break

        self.obs_label = objects_drawn

        for coordinate in picture_objects_coordinates:
            self.obs[coordinate] = 1


    def _generate_square(self, size: int, picture_objects_coordinates: set) -> set:
        """Generate a square of shape ``(size, size)`` in the scene.

        Args:
            size: length of the side of the square.
            picture_objects_coordinates: the coordinates of the objects
                already present in the scene.
        """
        coordinates = set() # the coordinates of the square

        valid_point = False
        # first generate the coordinates of
        # the upper left corner of the square.
        # we exclude some coordinates based on the
        # size of the observation and of the square.
        while not valid_point:
            upper_left_point = (np.random.randint(0, self.obs_dim + 1 - size),
                                np.random.randint(0, self.obs_dim + 1 - size))

            valid_point = not self._check_squares_intersection_adjacency(
                picture_objects_coordinates,
                set([upper_left_point]),
            )

        for x in range(size):
            for y in range(size):
                coordinates |= set(
                    [(upper_left_point[0] + x,
                     upper_left_point[1] + y)]
                )

        return coordinates

    @staticmethod
    def _check_squares_intersection_adjacency(picture_squares_coordinates: set,
                                              new_square_coordinates: set) -> bool:
        """The function checks that a newly generated square is not
        overlapping or adjacent with the squares already present
        in the scene.

        Args:
            picture_squares_coordinates: the coordinates describing
                the objects already in the scene.
            new_square_coordinates: the coordinates of the new square.

        Returns:
            A boolean value stating wether the new object is
            overlapping with or adjacent to other objects.
        """
        # check intersection
        if len(picture_squares_coordinates.intersection(new_square_coordinates)) > 0:
            return True

        # check adjacency
        for (x, y) in new_square_coordinates:
            if (
                    ((x + 1, y) in picture_squares_coordinates) or
                    ((x, y + 1) in picture_squares_coordinates) or
                    ((x - 1, y) in picture_squares_coordinates) or
                    ((x, y - 1) in picture_squares_coordinates)
            ):
                return True

        return False

    def _check_square_can_fit(self, square_size: int,
                              picture_squares_coordinates: set):
        """
        The method establishes whether a square of shape
        (square_size, square_size) can currently fit in the scene.
        It answers to the question: are there (square_size)*2
        lines, adjacent square_size by square_size, such that
        they intersecate in 4 points that are not in the scene?

        Args:
            square_size: the lenght of the square side.
            picture_squares_coordinates: the current occupied
                coordinates in the scene.

        Returns:
            True if a square of shape (square_size, square_size) can
            fit, False otherwise.
        """
        for col_start in range(0, self.obs_dim - square_size + 1):
            column_values = range(col_start, col_start + square_size)
            for row_start in range(0, self.obs_dim - square_size + 1):
                row_values = range(row_start, row_start + square_size)
                intersection_points = set(product(column_values, row_values))
                adjacency_points = set()
                for (x, y) in intersection_points:
                    candidate_adjacent_points = [(x, y + 1), (x, y - 1), (x - 1, y), (x + 1, y)]
                    for point in candidate_adjacent_points:
                        if self._point_out_of_picture(point) or (point in intersection_points):
                            continue
                        adjacency_points |= set([point])

                if ((len(intersection_points & picture_squares_coordinates) == 0)
                        and (len(adjacency_points & picture_squares_coordinates) == 0)):
                    return True
        return False

    @staticmethod
    def _point_out_of_picture(point: tuple) -> bool:
        if (point[0] < 0) or (point[1] < 0):
            return True
        return False

    @staticmethod
    def _plot_scene(scene_size: int, coordinates: set) -> None:
        """
        Generic method to plot a scene given the coordinates
        of the objects that appear therein.

        Args:
            scene_size: length of the scene side.
            coordinates: the objects coordinates.
        """
        scene = np.zeros((scene_size, scene_size))

        for c in coordinates:
            scene[c] += 1

        print(scene)

    def _softmax_action_selection(self, q_values, temperature):
        """Select an action given the q_values according to the
        softmax action selection method.

        Args:
            - q_values: output of the network
            - temperature: value of temperature parameter of the softmax function

        Returns:
            The action chosen.

        Todo:
            Debug.
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

    def _epsilon_greedy_action_selection(self, q_values, eps=.1):
        n_actions = len(self.actions_dict)

        sample = random.random()
        if sample > eps:
            action = q_values.max(1)[1].item()
            # max(1) is for batch, [1] is for index, .item() is for scalar
        else:
            action = random.randrange(n_actions)

        return action

    def _render(self, display_id=None):
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
        self._generate_observation()

        # reset external representation
        self.ext_repr = ExternalRepresentation(self.obs_dim, self.actions_dict)

        # Initialize Finger layers: Single 1 in 0-grid of shape dim x dim
        self.finger_layer_scene = FingerLayer(
            'scene',
            self.obs_dim,
            self.actions_dict,
            self.random_finger_position
        )
        self.finger_layer_repr = FingerLayer(
            'repr',
            self.obs_dim,
            self.actions_dict,
            self.random_finger_position
        )
        # reset whole state
        self._build_state()

        # reset counter of steps in an environment with a given scene
        self.step_counter = 0

        # reset flag for first label output
        # the agent gets positive reward only the first time
        # it outputs a label and it is correct
        self.first_label_output = True

        return torch.Tensor(self.state)

    def _build_state(self):
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

    def get_state_hash(self):
        flattened_state = self.state.flatten()
        string_state = ''.join([str(v) for v in flattened_state])
        return hash(string_state)

    @staticmethod
    def _get_curiosity_reward(n_visits: int, bending=.4, scale=.1) -> float:
        # the greater the bending parameter, the less bended is the curve
        # the greater the scale parameter, the larger the scale of the curve
        # with the default parameters, the prize for unvisited states is .1
        return (bending / (bending + n_visits)) * scale


class FingerLayer:
    """
    This class implements the finger movement part of the environment.
    """

    def __init__(self, layer_name, layer_dim, env_actions_dict, random_finger_position=False):
        self.layer_dim = layer_dim
        self.random_finger_position = random_finger_position
        self.fingerlayer = np.zeros((layer_dim, layer_dim))
        self.max_x = layer_dim - 1
        self.max_y = layer_dim - 1

        if self.random_finger_position:
            self.pos_x = random.randint(0, layer_dim - 1)  # random initial finger position
            self.pos_y = random.randint(0, layer_dim - 1)
        else:
            self.pos_x = 0  # fixed initial finger position
            self.pos_y = 0
        self.fingerlayer[self.pos_x, self.pos_y] = 1

        actions = [layer_name + a for a in ['_left', '_right', '_up', '_down']]
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

if __name__ == '__main__':
    from src.Reward import Reward

    reward_params = {
        'bad_label_punishment': False,
        'curiosity': False,
        'time_penalty': False,
    }

    env_params = {
        'max_CL_objects':           6,
        'CL_phases':                1,
        'max_episode_objects':      6,
        'obs_dim':                  6,
        'max_episode_length':       2,
        'default_eps':              .05,
        'n_actions':                9 + 3,
        'n_episodes_per_phase':     40000,
        'max_object_size':          5,
        'generate_random_nobj':     False,
        'random_object_size':       True,
        'random_finger_position':   False,
        'exponential_decay':        True,
        'exp_dec_steepness':        30,
    }

    reward = Reward(**reward_params)
    env = SingleAgentEnv(reward, **env_params)

    while(1):
        print(env.obs)
        print(env.obs_label)
        env.reset()